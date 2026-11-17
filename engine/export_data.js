'use strict';
// 포챔스 모드의 데이터를 JSON 으로 내보낸다: node engine/export_data.js data/champions
// 사용 가능 여부는 Showdown 의 팀 검증기(현재 규정 Reg M-C)가 판정한 결과를 그대로 쓴다.
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { dex, TeamValidator, FORMAT, ROOT } = require('./common');

const out = process.argv[2] || 'data/champions';
fs.mkdirSync(out, { recursive: true });
const v = TeamValidator.get(FORMAT);

const items = {}, moves = {}, abilities = {}, species = {};
for (const i of dex.items.all()) {
  if (i.isNonstandard) continue;
  items[i.id] = { id: i.id, name: i.name, shortDesc: i.shortDesc, mega: i.megaStone ? (typeof i.megaStone === 'string' ? [i.megaStone] : Object.values(i.megaStone)) : undefined, megaEvolves: i.megaEvolves || undefined };
}
for (const m of dex.moves.all()) {
  if (m.isNonstandard) continue;
  moves[m.id] = { id: m.id, name: m.name, type: m.type, category: m.category, basePower: m.basePower, accuracy: m.accuracy === true ? null : m.accuracy, pp: m.pp, priority: m.priority, target: m.target, shortDesc: m.shortDesc };
}
for (const a of dex.abilities.all()) {
  if (a.isNonstandard) continue;
  abilities[a.id] = { id: a.id, name: a.name, shortDesc: a.shortDesc };
}

const megaOf = {};   // 기본 종 id -> [{forme, item, types, abilities, baseStats}]
for (const s of dex.species.all()) {
  if (s.isNonstandard || !s.exists) continue;
  if (s.isMega && s.requiredItem) {
    const base = dex.species.get(s.baseSpecies).id;
    (megaOf[base] = megaOf[base] || []).push({ forme: s.name, id: s.id, item: dex.items.get(s.requiredItem).id, types: s.types, abilities: s.abilities, baseStats: s.baseStats });
  }
}

const mismatches = [];
for (const s of dex.species.all()) {
  if (s.isNonstandard || !s.exists || s.isMega || s.isPrimal || s.battleOnly || s.gen > 9) continue;
  // 습득 가능한 기술 후보: 학습 정보(진화 전 포함)에 있고 현재 버전에 존재하는 기술
  const lset = new Set();
  for (const e of dex.species.getFullLearnset(s.id)) for (const mid of Object.keys(e.learnset || {})) if (moves[mid]) lset.add(mid);
  if (!lset.size) continue;
  const ab = Object.values(s.abilities);
  const probe = { name: s.name, species: s.name, moves: [[...lset][0]], item: '', ability: ab[0], nature: 'Hardy', level: 50, evs: { hp: 2 }, ivs: {} };
  const problems = v.validateSet(probe, {});
  const legal = !problems || !problems.length;
  if (!legal && !/banned|Restricted|Mythical|does not exist|not available|illegal/i.test(problems.join(' '))) mismatches.push([s.name, problems[0]]);
  if (!legal) continue;
  species[s.id] = { id: s.id, name: s.name, baseSpecies: s.baseSpecies, num: s.num, types: s.types, baseStats: s.baseStats, abilities: s.abilities, weightkg: s.weightkg, moves: [...lset].sort(), megas: megaOf[dex.species.get(s.baseSpecies).id] && s.id === dex.species.get(s.baseSpecies).id ? megaOf[s.id] : (megaOf[s.id] || []) };
}

const commit = execSync('git rev-parse HEAD', { cwd: ROOT }).toString().trim();
const meta = { showdownCommit: commit, format: FORMAT, counts: { species: Object.keys(species).length, moves: Object.keys(moves).length, items: Object.keys(items).length, abilities: Object.keys(abilities).length }, rules: { statPointsPerStat: 32, statPointsTotal: 66, level: 50, bring: 6, pick: 3 } };
for (const [n, d] of Object.entries({ species, moves, items, abilities, meta })) fs.writeFileSync(path.join(out, n + '.json'), JSON.stringify(d));
console.log(JSON.stringify(meta));
if (mismatches.length) console.log('검토 필요(사유 불명으로 제외된 종):', JSON.stringify(mismatches.slice(0, 10)));
