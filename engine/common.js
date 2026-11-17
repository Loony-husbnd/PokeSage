'use strict';
// Showdown 로더. POKESAGE_SHOWDOWN 환경변수 또는 engine/.showdown 의 빌드(dist)를 쓴다.
const path = require('path');
const ROOT = process.env.POKESAGE_SHOWDOWN || path.join(__dirname, '.showdown');
const sim = require(path.join(ROOT, 'dist', 'sim'));
const { TeamValidator } = require(path.join(ROOT, 'dist', 'sim', 'team-validator'));

const FORMAT = '[Gen 9 Champions] BSS Reg M-C';          // 현재 싱글 규정 (검증용)
const SIM_FORMAT = '[Gen 9 Champions] Custom Game';        // 임의 상태 배틀용 (팀 크기 제약 없음, 챔피언스 모드)
const dex = sim.Dex.mod('champions');
const toID = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');

module.exports = { ROOT, sim, dex, TeamValidator, FORMAT, SIM_FORMAT, toID, Battle: sim.Battle, PRNG: sim.PRNG };
