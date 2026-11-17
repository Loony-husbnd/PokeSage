'use strict';
// 줄 단위 JSON 서버. 요청 한 줄 -> 응답 한 줄.
//   {cmd:'ping'} | {cmd:'validate', team:[set...]} | {cmd:'recommend', state, history, worlds, shard:[k,n], seed, maxTurns, eps}
const readline = require('readline');
const { dex, TeamValidator, FORMAT, toID, ROOT } = require('./common');
const { buildBattle, snapshot } = require('./world');
const { sampleSet } = require('./belief');
const { choose, legalChoices } = require('./policy');

function mulberry32(a) { return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

/** 상태의 상대 쪽을 추정 세트로 채운다. foe.mons: 관측한 포켓몬 + preview(상대 6마리 후보) 중 아직 안 나온 것에서 선출 */
function materializeFoe(foe, rng, variant) {
  const mons = foe.mons.map(m => ({ ...m, set: sampleSet({ species: m.species, revealed: m.revealed, megaed: m.megaed, megaForm: m.megaForm }, rng, variant) }));
  const need = Math.max(0, (foe.pick || 3) - mons.length);
  const seen = new Set(mons.map(m => toID(dex.species.get(m.species).baseSpecies)));
  const pool = (foe.preview || []).filter(s => !seen.has(toID(dex.species.get(s).baseSpecies)));
  for (let i = 0; i < need && pool.length; i++) {
    const s = pool.splice(Math.floor(rng() * pool.length), 1)[0];
    mons.push({ species: s, hp: 100, status: 'none', boosts: {}, active: false, set: sampleSet({ species: s, revealed: {} }, rng, variant) });
  }
  return { mons };
}

function materializeMe(me) {
  return { mons: me.mons.map(m => ({ ...m, set: m.set })) };
}

function eventsOf(lines) { return lines.filter(l => l.startsWith('|move|') || l.startsWith('|switch|') || l.startsWith('|-damage|') || l.startsWith('|faint|')); }

/** 한 턴 기록을 이 세계에서 다시 굴려 관측(체력 변화·행동 순서)과 맞는지 본다 */
function consistent(world, h, seed, tol) {
  const lines = [];
  const b = buildBattle(h.before.me, world.foeFor(h.before), h.before.field, seed, lines);
  const foeOpts = legalChoices(b.sides[1]);
  let foeChoice = null;
  if (h.foeMove) {
    const slot = b.sides[1].active[0].moveSlots.findIndex(s => s.id === toID(h.foeMove));
    if (slot < 0) return false;
    foeChoice = `move ${slot + 1}`;
    if (!foeOpts.includes(foeChoice)) return false;
  } else if (h.foeSwitchTo) {
    const idx = b.sides[1].pokemon.findIndex(p => toID(p.species.baseSpecies) === toID(dex.species.get(h.foeSwitchTo).baseSpecies));
    if (idx <= 0) return false; foeChoice = `switch ${idx + 1}`;
  } else return true;
  if (!b.choose('p1', h.myChoice) || !b.choose('p2', foeChoice)) return false;
  b.sendUpdates();
  if (h.first) {                                                  // 'me' | 'foe': 누가 먼저 움직였나
    const mv = lines.filter(l => l.startsWith('|move|'));
    if (mv.length >= 2) { const f = mv[0].startsWith('|move|p1') ? 'me' : 'foe'; if (f !== h.first) return false; }
  }
  const a = h.after || {};
  const pct = p => (p && p.hp > 0 ? Math.max(1, Math.floor(100 * p.hp / p.maxhp)) : 0);
  const meLead = b.sides[0].pokemon.find(p => p.name === b.sides[0].pokemon[0].name), foeLead = b.sides[1].pokemon[0];
  if (a.foeHp !== undefined && !h.foeSwitchTo && Math.abs(pct(foeLead) - a.foeHp) > tol) return false;
  if (a.meHp !== undefined && !h.foeSwitchTo && Math.abs(pct(meLead) - a.meHp) > tol) return false;
  return true;
}

function recommend(req) {
  const { state, history = [], worlds = 100, shard = [0, 1], seed = 1, maxTurns = 40, eps = 0.15, foeEps = 0.25, tolerance = 2 } = req;
  const [k, n] = shard;
  const totals = {}; let tried = 0, accepted = 0, relaxed = 0;
  let cands = null;
  for (let w = k; w < worlds; w += n) {
    const rng = mulberry32(seed * 1000003 + w * 7919 + 17);
    const variant = w === 0 ? 0 : 1;
    // 관측과 맞는 세계가 나올 때까지 몇 번 다시 뽑는다
    let foe = null, ok = false;
    for (let attempt = 0; attempt < 25 && !ok; attempt++) {
      tried++;
      foe = materializeFoe(state.foe, rng, attempt === 0 ? variant : 1);
      const world = { foeFor: before => ({ mons: foe.mons.map(m => { const bm = (before.foe.mons || []).find(x => toID(x.species) === toID(m.species) || toID(dex.species.get(x.species).baseSpecies) === toID(dex.species.get(m.species).baseSpecies)); return bm ? { ...m, hp: bm.hp, status: bm.status, boosts: bm.boosts, active: bm.active, megaed: bm.megaed } : { ...m, hp: 100, status: 'none', boosts: {}, active: false }; }) }) };
      ok = history.every((h, i) => consistent(world, h, [seed + i, w, 3, 9], tolerance));
    }
    if (ok) accepted++; else { relaxed++; }          // 끝내 못 맞추면 마지막 표본을 그대로 쓴다 (관측과 어긋남을 보고)
    const base = buildBattle(materializeMe(state.me), foe, state.field, [seed, w, 5, 7]);
    if (!base.sides[0].activeRequest) continue;
    const my = legalChoices(base.sides[0]);
    if (!cands) cands = my;
    const snap = snapshot(base);
    for (let ci = 0; ci < my.length; ci++) {
      const c = my[ci];
      const b = snap.restore([seed + 11, w, 13, 17]);
      const r2 = mulberry32(seed * 7 + w * 131 + 5);
      const foeFirst = choose(b, 1, r2, foeEps);
      if (!b.choose('p1', c) || (foeFirst && !b.choose('p2', foeFirst))) { continue; }
      b.sendUpdates();
      let turns = 0;
      while (!b.ended && turns++ < maxTurns) {
        let progressed = false;
        for (let s = 0; s < 2; s++) { const ch = choose(b, s, r2, s === 0 ? eps : foeEps); if (ch) { b.choose(s === 0 ? 'p1' : 'p2', ch); progressed = true; } }
        if (!progressed) break;
        b.sendUpdates();
      }
      let value;
      if (b.ended) value = b.winner === 'me' ? 1 : b.winner === 'foe' ? 0 : 0.5;
      else { const hpSum = s => b.sides[s].pokemon.reduce((a, p) => a + (p.fainted ? 0 : p.hp / p.maxhp), 0); value = 1 / (1 + Math.exp(-2.5 * (hpSum(0) - hpSum(1)))); }
      const t = totals[c] || (totals[c] = { n: 0, sum: 0, wins: 0, ended: 0 });
      t.n++; t.sum += value; if (b.ended) { t.ended++; if (b.winner === 'me') t.wins++; }
    }
  }
  return { totals, worlds: Math.ceil((worlds - k) / n), tried, accepted, relaxed };
}

function validate(team) {
  const v = TeamValidator.get(FORMAT);
  const sets = team.map(s => ({ name: s.species, species: s.species, ability: s.ability, item: s.item || '', moves: s.moves, nature: s.nature || 'Hardy', evs: s.evs || {}, ivs: {}, level: 50 }));
  if (sets.length === 6) return v.validateTeam(sets) || [];
  const out = [];
  for (const s of sets) { const p = v.validateSet(s, {}); if (p && p.length) out.push(...p); }
  return out;
}

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', line => {
  let req, res;
  try {
    req = JSON.parse(line);
    if (req.cmd === 'ping') res = { ok: true, pid: process.pid, showdown: ROOT };
    else if (req.cmd === 'validate') res = { ok: true, problems: validate(req.team) };
    else if (req.cmd === 'recommend') res = { ok: true, ...recommend(req) };
    else res = { ok: false, error: 'unknown cmd' };
  } catch (e) { res = { ok: false, error: String(e && e.stack || e) }; }
  res.id = req && req.id;
  process.stdout.write(JSON.stringify(res) + '\n');
});
