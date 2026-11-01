// Drives the editor page in jsdom with a stubbed API and checks the animation
// dropdown rules: only the box driving the viewer has a value; picking one
// blanks the others; a special auto-picks its first variant; blank -> standing.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync(require('path').join(__dirname, '..', '..', 'static', 'index.html'), 'utf8');
const calls = [];
const API = {
  '/api/info': { old_ready: [], dirty_bytes: 0 },
  '/api/charattr': {},
  '/api/animlist': { anims: [{ index: 0, label: 'Stand', frames: 6 }, { index: 1, label: 'Walk forward', frames: 6 }] },
  '/api/attackmoves': { moves: ['stand_Weak Punch', 'stand_Weak Punch (close)', 'stand_Medium Punch (forward)',
    'jump_Weak Kick (diagonal)', 'throw (forward + Strong Punch)',
    'special_Hadouken (Weak Punch)', 'special_Hadouken (Strong Punch)'] },
  '/api/projectiles': { moves: {} },
  '/api/stats': { stats: { walk_fwd: { value: 3, original: 3 }, walk_back: { value: 2, original: 2 } } },
  '/api/charanim': { frames: [] },
  '/api/attackanim': { frames: [] },
  '/api/movephys': null,
  '/api/frameinfo': { offset: '0x000000', dur: 2, original: 2, users: ['x'], editable: true },
  '/api/damagetable': { level: 16, table: '0x24E614', classes: [0, 1, 2].map(c => ({ class: c, base: 12 + 2 * c, original: 12 + 2 * c, levels: [] })) },
  '/api/damage': { addr: '0x19A3F4', class: 1, original_class: 1, base: 14, range: [11, 15], strength: 0, rand_rows: [0, 1],
                   classes: [0, 1, 2].map(c => ({ class: c, base: 12 + 2 * c })) },
  '/api/inputs/global': { ok: true, changed: 3, skipped: 0, dirty_bytes: 10 },
  '/api/inputs': { char: 'ryu', ver: 'new', key: 'ryu', checker_shared_with: [], moves: [
    { sub: '0x07FD6E', priority: 0, original_priority: 4, editable: true, kind: 'motion', name: 'Hadouken', button: 'P',
      motion: '1632143', original: '236', mode: 'engine', max_dirs: 16,
      timing: { dir: { min: 8, max: 15, orig_min: 8, orig_max: 15, extra: 0, fixed_engine: false }, btn: { light: 12, medium: 10, heavy: 8, orig: [12, 10, 8] } } },
    { sub: '0x07F8B8', priority: 1, original_priority: 0, editable: true, kind: 'motion', name: 'Tatsumaki', button: 'K',
      motion: '214', original: '214', mode: 'in place', max_dirs: 16 },
    { sub: '0x080BFA', priority: 2, original_priority: 2, editable: false, name: null, why: 'button move' },
    { sub: '0x083D8E', priority: 3, original_priority: 3, editable: true, kind: 'charge', name: 'Sonic Boom', button: 'P',
      motion: null, mode: 'original', describe: 'charge back, then forward + punch', max_dirs: 40,
      charge: [{ addr: '0x0981E0', frames: 60, original: 60, shared_with: [] }], release_shortcut: false,
      timing: { dir: { min: 8, max: 15, orig_min: 8, orig_max: 15, extra: 0, fixed_engine: false }, btn: null } },
    { sub: '0x081060', priority: 4, original_priority: 4, editable: true, kind: 'mash', name: 'Hundred Hand Slap', button: 'P',
      describe: 'press punch 4 times quickly', mash: ['light', 'medium', 'heavy'].map((st, i) =>
        ({ strength: st, window: 15 - 3 * i, count: 4, orig_window: 15 - 3 * i, orig_count: 4 })) } ] },
};
const posts = [];
function fakeFetch(url, opts) {
  const path = String(url).split('?')[0];
  calls.push(String(url));
  if (opts && opts.body) posts.push([path, JSON.parse(opts.body)]);
  const body = API[path];
  return Promise.resolve({ ok: body !== null && body !== undefined, status: body ? 200 : 404,
    json: () => Promise.resolve(body || { error: 'x' }), headers: { get: () => null },
    blob: () => Promise.resolve(null) });
}
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true,
  beforeParse(w) {
    w.fetch = fakeFetch;
    w.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, { get: () => () => ({}) });
    w.createImageBitmap = () => Promise.resolve({});
  } });
const w = dom.window, $ = id => w.document.getElementById(id);
const tick = () => new Promise(r => setTimeout(r, 30));
const vals = () => ['a_index', 'a_move', 'a_special', 'a_variant'].map(id => $(id).value);
let fails = 0;
function expect(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(got)}${ok ? '' : ' (want ' + JSON.stringify(want) + ')'}`);
}
function pick(id, value) { $(id).value = value; $(id).dispatchEvent(new w.Event('change')); }

(async () => {
  for (let i = 0; i < 20; i++) await tick();
  expect('on load only movement shows Stand', vals(), ['0', '', '', '']);
  expect('blank entries exist', ['a_index', 'a_move', 'a_special'].map(id => $(id).options[0].value), ['', '', '']);

  pick('a_move', 'stand_Weak Punch'); for (let i = 0; i < 5; i++) await tick();
  expect('normal selected -> others blank', vals(), ['', 'stand_Weak Punch', '', '']);

  pick('a_special', 'Hadouken'); for (let i = 0; i < 5; i++) await tick();
  expect('special auto-picks first variant, others blank', vals(), ['', '', 'Hadouken', 'special_Hadouken (Weak Punch)']);

  pick('a_variant', 'special_Hadouken (Strong Punch)'); for (let i = 0; i < 5; i++) await tick();
  expect('variant change keeps the special', vals(), ['', '', 'Hadouken', 'special_Hadouken (Strong Punch)']);

  pick('a_index', '1'); for (let i = 0; i < 5; i++) await tick();
  expect('movement selected -> special + variant blank', vals(), ['1', '', '', '']);
  expect('variant list emptied with no special', $('a_variant').disabled, true);

  pick('a_move', 'stand_Weak Punch'); for (let i = 0; i < 5; i++) await tick();
  pick('a_move', ''); for (let i = 0; i < 5; i++) await tick();
  expect('blank chosen -> back to standing', vals(), ['0', '', '', '']);
  expect('standing anim was requested', calls.filter(c => c.startsWith('/api/charanim?anim=0')).length >= 2, true);

  // damage: the global table renders one input per class; an attack box shows its class
  expect('damage table inputs', $('dtFields').querySelectorAll('input').length, 3);
  w.eval(`animFrames=[{offset:0x110162,dur:2,obj_ptr:0,boxes:{attack:{addr:'0x19A3F4',val_x:0,val_y:0,rad_x:1,rad_y:1}}}]; animPos=0; selBox='attack'; syncFields();`);
  for (let i = 0; i < 5; i++) await tick();
  expect('attack box shows damage row', $('dmgRow').hidden, false);
  expect('damage class selected', $('f_dmgclass').value, '1');
  expect('damage note mentions range', /11–15/.test($('dmgNote').textContent), true);
  w.eval(`selBox='vuln0'; animFrames[0].boxes.vuln0={addr:'0x19883C',val_x:0,val_y:0,rad_x:1,rad_y:1}; syncFields();`);
  for (let i = 0; i < 3; i++) await tick();
  expect('hurtbox hides damage row', $('dmgRow').hidden, true);

  // special move inputs: one main row per checker in priority order (plus a
  // second row of fields under it), locked until edit mode
  const all = [...$('inpTab').querySelectorAll('tbody tr')];
  const main = all.filter(r => !r.querySelector('td.inpextra'));
  const extraOf = r => { const n = r.nextElementSibling; return n && n.querySelector('td.inpextra') ? n : null; };
  expect('one main row per move', main.length, 5);
  expect('first row is the moved-up Hadouken', main[0].children[1].textContent, '1. Hadouken *');
  expect('pretzel shown as arrows', main[0].children[3].textContent, '↙→↘↓↙←↘ + punch (was ↓↘→)');
  expect('motion input locked when not editing', main[0].querySelector('input').disabled, true);
  expect('non-editable row has no input', main[2].querySelector('input'), null);
  expect('charge move: empty motion box + game input in words', [main[3].querySelector('input').placeholder, main[3].children[3].textContent],
    ['game input', 'charge back, then forward + punch']);
  const sbx = [...extraOf(main[3]).querySelectorAll('input')];
  expect('charge move: release shortcut, dir window min/max, charge time', sbx.map(i => i.type === 'checkbox' ? String(i.checked) : i.value),
    ['false', '8', '15', '60']);
  const hx = [...extraOf(main[0]).querySelectorAll('input')];
  expect('motion move: shortcuts box + dir window + L/M/H button windows', hx.map(i => i.type === 'checkbox' ? String(i.checked) : i.value),
    ['false', '8', '15', '12', '10', '8']);
  expect('mash move: presses + 3 windows', [...extraOf(main[4]).querySelectorAll('input')].map(i => i.value), ['4', '15', '12', '9']);
  expect('shortcut helpers', [w.eval("toggleShortcuts('236', true)"), w.eval("toggleShortcuts('2*36*', false)"),
    w.eval("hasShortcuts('2*36*')"), w.eval("hasShortcuts('2*36')")], ['2*36*', '236', true, false]);
  w.eval('toggleEdit()');
  expect('motion input unlocked in edit mode', main[0].querySelector('input').disabled, false);
  expect('timing fields unlocked in edit mode', hx.every(i => !i.disabled), true);
  expect('top row cannot move up', main[0].querySelector('button').disabled, true);
  expect('second row can move up', main[1].querySelector('button').disabled, false);
  expect('global leniency buttons unlocked', [...w.document.querySelectorAll('[data-gedit]')].every(e => !e.disabled), true);
  posts.length = 0;
  await w.eval("globalInputs({action:'shortcuts_on'}, 'Shortcuts on')");
  expect('global shortcuts posts the action', posts.filter(p => p[0] === '/api/inputs/global').map(p => p[1].action), ['shortcuts_on']);
  w.eval('toggleEdit()');

  // normals dropdown headings
  const groups = [...$('a_move').querySelectorAll('optgroup')].map(g =>
    [g.label, [...g.querySelectorAll('option')].map(o => o.value)]);
  expect('normals grouped under headings', groups, [
    ['Far normals', ['stand_Weak Punch', 'jump_Weak Kick (diagonal)']],
    ['Close normals', ['stand_Weak Punch (close)']],
    ['Command normals', ['stand_Medium Punch (forward)']],
    ['Throws', ['throw (forward + Strong Punch)']]]);

  // tabs: global cards live on the Global tab, not the Character tab
  const cardIn = (view, title) => [...$(view).querySelectorAll('.card h2')].some(h => h.textContent.includes(title));
  expect('global cards on Global tab', ['Health', 'Stun', 'Dizzy', 'Damage table', 'Game speed'].map(t => cardIn('view-global', t)), [true, true, true, true, true]);
  expect('no global cards on Character tab', ['Health', 'Stun', 'Dizzy', 'Damage table', 'Game speed'].some(t => cardIn('view-anim', t)), false);
  expect('Theory Fighter tab exists', !!$('view-theory') && !!$('tabTheory'), true);
  w.eval("showTab('global')");
  expect('Global tab shows', [$('view-global').style.display, $('view-anim').style.display], ['', 'none']);
  w.eval("showTab('anim')");

  // collapsible cards: all collapsed at start except Character (and single-card tabs)
  const open = [...w.document.querySelectorAll('#view-anim .card, #view-global .card')]
    .filter(c => !c.classList.contains('collapsed')).map(c => c.querySelector('h2').textContent.trim());
  expect('only Character starts open', open, ['Character']);
  const hb = [...$('view-anim').querySelectorAll('.card')].find(c => c.textContent.includes('Hitbox editing'));
  hb.querySelector('.cardtog').click();
  expect('clicking a title expands it', [hb.classList.contains('collapsed'), hb.querySelector('.cardtog').getAttribute('aria-expanded')], [false, 'true']);
  hb.querySelector('.cardtog').click();
  expect('clicking again collapses it', hb.classList.contains('collapsed'), true);

  // secret buttons
  const before = calls.length;
  await w.eval('secretDiscard()');
  expect('secret discard posts reload without a prompt', calls.slice(before).includes('/api/reload'), true);

  // SNK mode: Hadouken -> pretzel, other editable moves -> other long motions
  posts.length = 0;
  await w.eval('secretCrazy()');
  const ip = posts.filter(p => p[0] === '/api/inputs').map(p => [p[1].sub, p[1].motion]);
  expect('SNK mode: each motion/charge move set once (not mash), Hadouken = pretzel', ip.map(x => x[0]), ['0x07FD6E', '0x07F8B8', '0x083D8E']);
  expect('SNK mode: Hadouken = pretzel', ip[0][1], '1632143');
  expect('SNK mode: Tatsumaki gets a long SNK motion', ip[1] && ip[1][1].length >= 6 && ip[1][1] !== '1632143', true);

  console.log(fails ? `${fails} FAILED` : 'ALL PASSED');
  process.exit(fails ? 1 : 0);
})();
