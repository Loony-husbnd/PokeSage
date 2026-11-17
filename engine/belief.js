'use strict';
// 상대 숨은 정보 추정: 특성, 도구, 기술, 스탯 포인트·성격. 관측한 것은 고정하고 나머지를 표본 추출한다.
const { dex, toID } = require('./common');
const fs = require('fs');
const path = require('path');

const DATA = process.env.POKESAGE_DATA || path.join(__dirname, '..', 'data', 'champions');
const SPECIES = JSON.parse(fs.readFileSync(path.join(DATA, 'species.json')));
const MOVES = JSON.parse(fs.readFileSync(path.join(DATA, 'moves.json')));
const ITEMS = JSON.parse(fs.readFileSync(path.join(DATA, 'items.json')));

const UTILITY = new Set(['recover', 'roost', 'softboiled', 'slackoff', 'moonlight', 'synthesis', 'shoreup', 'protect', 'toxic', 'willowisp', 'thunderwave', 'swordsdance', 'nastyplot', 'calmmind', 'dragondance', 'bulkup', 'quiverdance', 'shellsmash', 'irondefense', 'stealthrock', 'spikes', 'substitute', 'taunt', 'knockoff', 'uturn', 'voltswitch', 'leechseed', 'reflect', 'lightscreen', 'trickroom', 'tailwind', 'fakeout', 'closecombat', 'partingshot', 'encore', 'haze', 'wish', 'bellydrum', 'agility', 'rockpolish', 'glare', 'spore', 'sleeppowder']);

// 도구 사전 확률 (포챔스에 존재하는 도구만 사용한다)
const ITEM_PRIOR = [['leftovers', 0.14], ['lifeorb', 0.1], ['sitrusberry', 0.14], ['focussash', 0.1], ['choicescarf', 0.08], ['expertbelt', 0.04], ['rockyhelmet', 0.04], ['lumberry', 0.06], ['scopelens', 0.01], ['quickclaw', 0.01], ['mentalherb', 0.02], ['whiteherb', 0.01], ['shellbell', 0.01], ['wiseglasses', 0.02], ['muscleband', 0.02]];

// 스탯 포인트 유형 (합계 66, 스탯당 최대 32)
const SPREADS = {
  physFast: { w: 3, evs: { hp: 2, atk: 32, spe: 32 }, natures: ['Jolly', 'Adamant'] },
  specFast: { w: 3, evs: { hp: 2, spa: 32, spe: 32 }, natures: ['Timid', 'Modest'] },
  physBulk: { w: 2, evs: { hp: 32, atk: 32, def: 2 }, natures: ['Adamant', 'Impish'] },
  specBulk: { w: 2, evs: { hp: 32, spa: 32, spd: 2 }, natures: ['Modest', 'Calm'] },
  wall: { w: 1.5, evs: { hp: 32, def: 17, spd: 17 }, natures: ['Bold', 'Calm', 'Impish', 'Careful'] },
  physSlow: { w: 1, evs: { hp: 2, atk: 32, def: 32 }, natures: ['Brave', 'Adamant'] },
};

function pickW(list, rng) { const t = list.reduce((a, [, w]) => a + w, 0); let r = rng() * t; for (const [v, w] of list) { r -= w; if (r <= 0) return v; } return list[list.length - 1][0]; }

function attackScore(sp, m) {
  if (m.category === 'Status') return 0;
  let bp = m.basePower || 60; const acc = (m.accuracy || 100) / 100;
  const stab = sp.types.includes(m.type) ? 1.5 : 1;
  const phys = sp.baseStats.atk >= sp.baseStats.spa;
  const cat = (m.category === 'Physical') === phys ? 1 : 0.35;
  const dm = dex.moves.get(m.id);
  if (dm.multihit) bp *= Array.isArray(dm.multihit) ? 3 : dm.multihit;
  if (dm.flags && (dm.flags.charge || dm.flags.recharge)) bp *= 0.6;
  if (dm.selfdestruct) bp *= 0.25;
  if (dm.ohko) bp = 0;
  return bp * acc * stab * cat;
}

function fillMoves(sp, known, rng, variant) {
  const out = known.filter(id => MOVES[id]).slice(0, 4);
  if (out.length >= 4) return out;
  const pool = sp.moves.filter(id => !out.includes(id));
  const attacks = pool.map(id => ({ id, s: attackScore(sp, MOVES[id]) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s);
  const util = pool.filter(id => UTILITY.has(id));
  const take = (list, n, spread) => { const r = []; const top = list.slice(0, Math.max(n, spread)); while (r.length < n && top.length) r.push(top.splice(Math.floor(rng() * Math.min(top.length, variant === 0 ? 1 : top.length)), 1)[0]); return r; };
  const slots = 4 - out.length;
  const nAtk = Math.min(slots, Math.max(2, slots - (util.length ? 1 : 0)));
  for (const a of take(attacks, nAtk, 7)) out.push(a.id);
  const u = util.slice(); while (out.length < 4 && u.length) { const x = u.splice(Math.floor(rng() * u.length * (variant === 0 ? 0.3 : 1)), 1)[0]; if (!out.includes(x)) out.push(x); }
  for (const a of attacks) { if (out.length >= 4) break; if (!out.includes(a.id)) out.push(a.id); }
  for (const id of pool) { if (out.length >= 1) break; out.push(id); }
  return out.slice(0, 4);
}

/**
 * 한 포켓몬의 추정 세트. info: { species, revealed:{moves,ability,item,itemGone}, megaed }
 * 관측된 값은 그대로 쓴다. variant 0 은 가장 그럴듯한 하나, 그 이상은 무작위 표본.
 */
function sampleSet(info, rng, variant) {
  const sp = SPECIES[toID(info.species)] || SPECIES[toID(dex.species.get(info.species).baseSpecies)];
  if (!sp) throw new Error(`포챔스에 없는 종: ${info.species}`);
  const rev = info.revealed || {};
  let species = sp.name, ability = rev.ability, item = rev.item;
  const megas = sp.megas || [];
  if (info.megaed) {
    const mg = megas.find(m => m.forme === info.megaForme) || megas.find(m => m.item === item) || megas[0];
    if (mg) { species = mg.forme; item = mg.item; ability = Object.values(mg.abilities)[0]; }
  } else {
    if (!ability) { const ab = Object.entries(sp.abilities).map(([k, v]) => [v, k === 'H' ? 0.25 : 0.5]); ability = variant === 0 ? Object.values(sp.abilities)[0] : pickW(ab, rng); }
    if (item === undefined || item === null) {
      const stone = megas.length && rng() < (variant === 0 ? 0 : 0.45) ? megas[Math.floor(rng() * megas.length)].item : null;
      item = stone || (variant === 0 ? 'leftovers' : pickW([...ITEM_PRIOR, ['', 0.12]], rng));
    }
    if (rev.itemGone) item = '';
  }
  const names = Object.keys(SPREADS);
  const sk = variant === 0 ? (sp.baseStats.atk >= sp.baseStats.spa ? 'physFast' : 'specFast') : pickW(names.map(n => [n, SPREADS[n].w]), rng);
  const spr = SPREADS[sk];
  const nature = spr.natures[Math.floor(rng() * spr.natures.length)];
  return { species, ability, item: item || '', moves: fillMoves(sp, rev.moves || [], rng, variant), nature, evs: { ...spr.evs }, spreadKey: sk };
}

module.exports = { sampleSet, SPECIES, MOVES, ITEMS, ITEM_PRIOR };
