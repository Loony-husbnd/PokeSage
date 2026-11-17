'use strict';
// 롤아웃 정책: 합법 선택지 중 대미지 어림값·변화기 가치·교체 상성으로 점수를 매겨 고른다.
const { dex } = require('./common');

const SETUP = new Set(['swordsdance', 'nastyplot', 'calmmind', 'dragondance', 'bulkup', 'quiverdance', 'shellsmash', 'irondefense', 'agility', 'rockpolish', 'bellydrum', 'curse', 'coil', 'workup', 'growth', 'tailglow']);
const HEAL = new Set(['recover', 'roost', 'softboiled', 'slackoff', 'moonlight', 'synthesis', 'shoreup', 'wish', 'milkdrink', 'healorder', 'rest']);
const STATUS_MOVES = { toxic: 'tox', willowisp: 'brn', thunderwave: 'par', glare: 'par', spore: 'slp', sleeppowder: 'slp', hypnosis: 'slp', yawn: 'slp', nuzzle: 'par' };
const STAGE = s => (s >= 0 ? (2 + s) / 2 : 2 / (2 - s));

function statOf(p, k) { return Math.floor((p.storedStats[k] || 100) * STAGE(p.boosts[k] || 0)); }

function effectiveness(type, defTypes) {
  if (!dex.getImmunity(type, defTypes)) return 0;
  return Math.pow(2, dex.getEffectiveness(type, defTypes));
}

/** 공격자 a 의 기술 m 이 방어자 d 에게 주는 평균 대미지 비율(방어자 최대 HP 대비) */
function dmgFrac(a, mv, d) {
  if (mv.category === 'Status' || !mv.basePower) return 0;
  const phys = mv.category === 'Physical';
  let atk = statOf(a, phys ? 'atk' : 'spa'), def = statOf(d, phys ? 'def' : 'spd');
  if (phys && a.status === 'brn') atk = Math.floor(atk / 2);
  const dt = d.getTypes();
  const eff = effectiveness(mv.type, dt);
  if (!eff) return 0;
  let bp = mv.basePower;
  if (mv.multihit) bp *= Array.isArray(mv.multihit) ? 3 : mv.multihit;
  const base = Math.floor(Math.floor((22 * bp * atk) / Math.max(def, 1)) / 50) + 2;
  const stab = a.getTypes().includes(mv.type) ? 1.5 : 1;
  const acc = mv.accuracy === true ? 1 : (mv.accuracy || 100) / 100;
  let v = base * 0.925 * stab * eff * acc;
  if (a.item === 'lifeorb') v *= 1.3;
  if (/^choice(band|specs)$/.test(a.item)) v *= 1.5;
  return v / d.maxhp;
}

function bestDmg(a, d) {
  let best = 0;
  for (const slot of a.moveSlots) best = Math.max(best, dmgFrac(a, dex.moves.get(slot.id), d));
  return best;
}

function speedOf(p) { return statOf(p, 'spe') * (p.status === 'par' ? 0.5 : 1); }

const alive = p => !p.fainted && p.hp > 0;

function legalChoices(side) {
  const req = side.activeRequest;
  if (!req || req.wait) return [];
  if (req.teamPreview) return ['default'];
  const sw = req.side.pokemon.map((p, i) => ({ p, i })).filter(({ p }) => !p.active && !/ fnt$/.test(p.condition) && p.condition !== '0 fnt').map(({ i }) => `switch ${i + 1}`);
  if (req.forceSwitch) return sw;
  const act = req.active[0], out = [];
  act.moves.forEach((m, i) => { if (!m.disabled) { out.push(`move ${i + 1}`); if (act.canMegaEvo) out.push(`move ${i + 1} mega`); } });
  if (!act.trapped) out.push(...sw);
  return out;
}

/** 선택 문자열 -> 점수. self: 내 활성, foe: 상대 활성 */
function score(side, choice, self, foe, rng) {
  const req = side.activeRequest;
  const m = /^move (\d+)( mega)?$/.exec(choice);
  if (m) {
    const slot = self.moveSlots[Number(m[1]) - 1];
    const mv = dex.moves.get(slot.id);
    let s;
    const hpf = self.hp / self.maxhp, foeHp = foe.hp / foe.maxhp;
    const fast = speedOf(self) >= speedOf(foe) || mv.priority > 0;
    if (mv.category !== 'Status') {
      const d = dmgFrac(self, mv, foe);
      s = Math.min(d, foeHp);
      if (d >= foeHp) s += fast ? 0.6 : 0.3;                      // KO 가능
      if (mv.priority > 0 && d >= foeHp) s += 0.3;
      if (mv.selfdestruct) s *= 0.3;
      if (mv.flags && mv.flags.recharge) s *= 0.8;
    } else if (SETUP.has(mv.id)) {
      s = hpf > 0.6 && bestDmg(foe, self) < 0.5 * hpf ? 0.28 : 0.02;
    } else if (HEAL.has(mv.id)) {
      s = hpf < 0.5 ? 0.45 : 0.02;
    } else if (STATUS_MOVES[mv.id]) {
      s = !foe.status && effectiveness('Normal', foe.getTypes()) && hpf > 0.3 ? 0.22 : 0;
    } else if (mv.id === 'protect' || mv.id === 'detect') {
      s = 0.08;
    } else if (/stealthrock|spikes|toxicspikes|stickyweb/.test(mv.id)) {
      s = 0.15;
    } else s = 0.06;
    if (m[2]) s += 0.2;                                           // 메가진화는 거의 항상 이득
    return s + rng() * 0.02;
  }
  const sm = /^switch (\d+)$/.exec(choice);
  if (sm) {
    const target = req.side.pokemon[Number(sm[1]) - 1];
    const bench = side.pokemon.find(p => p.name === target.ident.split(': ')[1]) || side.pokemon[Number(sm[1]) - 1];
    const off = Math.min(bestDmg(bench, foe), 1) , def = bestDmg(foe, bench) / Math.max(bench.hp / bench.maxhp, 0.01);
    const outmatched = bestDmg(foe, self) >= self.hp / self.maxhp * 0.9 && bestDmg(self, foe) < foe.hp / foe.maxhp;
    return (outmatched ? 0.1 : -0.15) + 0.45 * (off - def) + rng() * 0.02;
  }
  return 0;
}

/** 정책: 점수 상위 선택. eps 확률로 상위 3개 중 무작위 */
function choose(battle, sideIdx, rng, eps) {
  const side = battle.sides[sideIdx];
  const opts = legalChoices(side);
  if (!opts.length) return null;
  if (opts.length === 1) return opts[0];
  const req = side.activeRequest;
  if (req.forceSwitch) {
    const foe = battle.sides[1 - sideIdx].active[0];
    const ranked = opts.map(c => { const t = req.side.pokemon[Number(c.split(' ')[1]) - 1]; const p = side.pokemon.find(x => x.name === t.ident.split(': ')[1]); return [c, foe ? Math.min(bestDmg(p, foe), 1) - bestDmg(foe, p) / Math.max(p.hp / p.maxhp, 0.01) : 0]; }).sort((a, b) => b[1] - a[1]);
    return ranked[0][0];
  }
  const self = side.active[0], foe = battle.sides[1 - sideIdx].active[0];
  if (!self || !foe) return opts[0];
  const ranked = opts.map(c => [c, score(side, c, self, foe, rng)]).sort((a, b) => b[1] - a[1]);
  if (rng() < eps) return ranked[Math.floor(rng() * Math.min(3, ranked.length))][0];
  return ranked[0][0];
}

module.exports = { choose, legalChoices, bestDmg, dmgFrac };
