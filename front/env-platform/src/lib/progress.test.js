import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatElapsed,
  isTerminalStatus,
  nextBarPercent,
  pollDelay,
  stageStates,
  stagesForMode,
} from './progress.js';

test('stage text and checklist follow the current polled stage', () => {
  const stages = stagesForMode('standard', 'air_quality');
  assert.equal(stages.find((stage) => stage.key === 'removing_duplicate_headers').label, 'Removing duplicate headers and empty columns');
  assert.deepEqual(stageStates(stages, 'checking_ranges', 'processing').slice(1, 7), [
    'done',
    'done',
    'done',
    'done',
    'active',
    'pending',
  ]);
});

test('IMD adds a merging stage with file counts', () => {
  const stages = stagesForMode('imd', 'rainfall');
  assert.equal(stages[2].key, 'merging_files');
  assert.equal(stages[2].label, 'Merging files');
});

test('bar percent never decreases and never reaches 100 before completion', () => {
  let percent = 0;
  const updates = [
    { phase: 'uploading', uploadPercent: 4 },
    { phase: 'uploading', uploadPercent: 10 },
    { phase: 'processing', percent: 12 },
    { phase: 'processing', percent: 26 },
    { phase: 'processing', percent: 20 },
    { phase: 'processing', percent: 99 },
  ];
  for (const update of updates) {
    const next = nextBarPercent(percent, update);
    assert.ok(next >= percent);
    assert.ok(next < 100);
    percent = next;
  }
  assert.equal(percent, 99);
  assert.equal(nextBarPercent(percent, { phase: 'completed', percent: 100 }), 100);
});

test('terminal states stop polling', () => {
  assert.equal(isTerminalStatus('completed'), true);
  assert.equal(isTerminalStatus('failed'), true);
  assert.equal(isTerminalStatus('cancelled'), true);
  assert.equal(isTerminalStatus('processing'), false);
});

test('polling backs off after thirty seconds', () => {
  assert.equal(pollDelay(1000), 1000);
  assert.equal(pollDelay(30_001), 2500);
});

test('elapsed time formats as minutes and seconds', () => {
  assert.equal(formatElapsed(0), '0:00');
  assert.equal(formatElapsed(65), '1:05');
  assert.equal(formatElapsed(3661), '1:01:01');
});
