'use strict';
// 상태(JSON) -> Showdown 배틀. 내 쪽은 정확하게, 상대 쪽은 추정한 세트로 채운 "가려진 세계"를 만든다.
const { dex, Battle, PRNG, SIM_FORMAT, toID } = require('./common');

const STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const IVS = { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31 };

function toSet(s) {
  const evs = { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 };
  Object.assign(evs, s.evs || {});
  return { name: s.species, species: s.species, ability: s.ability, item: s.item || '', moves: s.moves.slice(0, 4), nature: s.nature || 'Hardy', evs, ivs: { ...IVS }, level: 50, gender: '' };
}

/**
 * side 정의: { mons: [{set, hp(%), status, boosts, active, megaed, fainted, lastMove}], conditions: [...] }
 * 살아 있는 포켓몬만 넣고 선두를 맨 앞에 둔다. 이미 메가진화한 포켓몬은 메가 폼으로 만든다.
 */
function normalizeMons(mons) {
  const alive = mons.filter(m => !m.fainted && m.hp > 0);
  const lead = alive.findIndex(m => m.active);
  if (lead > 0) alive.unshift(alive.splice(lead, 1)[0]);
  return alive;
}

function patchMon(p, m) {
  const maxhp = p.maxhp;
  p.hp = Math.max(1, Math.min(maxhp, Math.round(maxhp * m.hp / 100)));
  if (m.status && m.status !== 'none') p.setStatus(m.status, null, null, true);
  for (const [k, v] of Object.entries(m.boosts || {})) if (v) p.boosts[k] = Math.max(-6, Math.min(6, v));
}

function applyField(b, field, sides) {
  if (!field) return;
  const tryDo = f => { try { f(); } catch (e) { /* 구현되지 않은 필드는 무시 */ } };
  if (field.weather) tryDo(() => b.field.setWeather(field.weather));
  if (field.terrain) tryDo(() => b.field.setTerrain(field.terrain));
  for (const pw of field.pseudo || []) tryDo(() => b.field.addPseudoWeather(pw));
  for (const [i, conds] of [[0, field.me || []], [1, field.foe || []]]) {
    const side = b.sides[i], src = side.active[0];
    for (const c of conds) {
      const [id, layers] = String(c).split(':');
      for (let n = 0; n < (Number(layers) || 1); n++) tryDo(() => side.addSideCondition(id, src));
    }
  }
}

/** 팀 둘과 필드로 배틀을 만들고 상태를 덮어쓴다. seed: 숫자 4개. */
function buildBattle(meSide, foeSide, field, seed, lines) {
  const me = normalizeMons(meSide.mons), foe = normalizeMons(foeSide.mons);
  const b = new Battle({
    formatid: SIM_FORMAT, seed,
    p1: { name: 'me', team: me.map(m => toSet(m.set)) },
    p2: { name: 'foe', team: foe.map(m => toSet(m.set)) },
    send: lines ? (t, d) => { if (t === 'update') lines.push(...(Array.isArray(d) ? d.join('\n') : d).split('\n')); } : undefined,
  });
  b.choose('p1', 'default'); b.choose('p2', 'default'); b.sendUpdates();
  [me, foe].forEach((arr, si) => {
    const side = b.sides[si];
    arr.forEach((m, i) => patchMon(side.pokemon[i], m));
    if (arr.some(m => m.megaed)) for (const p of side.pokemon) p.canMegaEvo = null;      // 한 판에 한 번
    const lead = side.pokemon[0], lm = arr[0].lastMove;
    if (lm && /^choice/.test(lead.item)) { try { lead.addVolatile('choicelock'); lead.volatiles.choicelock.move = toID(lm); } catch (e) { /* 무시 */ } }
  });
  applyField(b, field);
  if (lines) lines.length = 0;
  b.makeRequest(b.requestState);
  return b;
}

function snapshot(b) {
  const json = JSON.stringify(b.toJSON());
  return { restore(seed, lines) {
    const c = Battle.fromJSON(JSON.parse(json));
    c.prng = new PRNG(seed);
    if (lines) c.send = (t, d) => { if (t === 'update') lines.push(...(Array.isArray(d) ? d.join('\n') : d).split('\n')); };
    return c;
  } };
}

module.exports = { buildBattle, snapshot, toSet, normalizeMons, STATS };
