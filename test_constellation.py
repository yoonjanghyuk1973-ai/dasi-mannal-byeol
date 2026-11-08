import pathlib, subprocess, sys, unittest, zipfile

ROOT = pathlib.Path(__file__).resolve().parent
HTML = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')


def groups_source():
    start = HTML.index('const CONS=')
    end = HTML.index('let PZ=0')
    return HTML[start:end]


CASES = r'''
const src = process.argv[1];
eval(src+'\nif(CONS[0].n!=="북두칠성"||CONS[0].p.length!==7||CONS[0].l.length!==7) throw new Error("dipper frame")');
function plan(ps){
  const {groups,cur,done,def}=constellationGroups(ps);
  return {
    def: groups[def].c.t,
    current: groups[cur].c.t,
    switcher: done ? groups.slice(0,done).map(g=>g.c.t) : [],
    placed: groups.map(g=>({name:g.c.t, ids:g.g.map(p=>p.id)})),
  };
}
function pet(id, example, name){return {id, example, name, photo:'/uploads/x.jpg', letter:'편지', owner:'보호', ekey:'key', visibility:'public'};}
const examples=[1,2,3,4,5,6].map(id=>pet(id,1,'[예시] 샘플'+id));
function check(name, actual, expected){
  const ok = JSON.stringify(actual)===JSON.stringify(expected);
  if(!ok){ console.error(name, JSON.stringify(actual)); process.exitCode=1; }
}
// Fewer than 7 non-example public pets: no switcher, only 북두칠성 exists as the open page.
let view=plan(examples.concat([pet(7,0,'실1'), pet(8,0,'실2')]));
check('partial dipper', view, {
  def:'북두칠성', current:'북두칠성', switcher:[],
  placed:[{name:'북두칠성', ids:[7,8]}],
});
// A real registration whose name merely looks like a sample stays in the sky.
const named=pet(9,0,'[예시] 아니지만 실제');
const snapshot=JSON.stringify(named);
view=plan([named].concat(examples));
if(JSON.stringify(named)!==snapshot){ console.error('mutated'); process.exitCode=1; }
check('name is not the sample flag', view.placed, [{name:'북두칠성', ids:[9]}]);
// Exactly 7 fills 북두칠성 and announces 카시오페이아, but does not offer it as a button.
view=plan(examples.concat([1,2,3,4,5,6,7].map(n=>pet(10+n,0,'실'+n))));
check('full dipper', {def:view.def, current:view.current, switcher:view.switcher, first:view.placed[0].ids.length, second:view.placed[1].ids},
  {def:'북두칠성', current:'카시오페이아', switcher:['북두칠성'], first:7, second:[]});
// The 8th non-example public pet is what makes 카시오페이아 the open page. Its chip is not in the switcher.
view=plan([1,2,3,4,5,6,7,8].map(n=>pet(n,0,'실'+n)));
check('cassiopeia opens', {def:view.def, current:view.current, switcher:view.switcher, cass:view.placed[1]},
  {def:'카시오페이아', current:'카시오페이아', switcher:['북두칠성'], cass:{name:'카시오페이아', ids:[8]}});
// Completed 카시오페이아 becomes a chip. The empty next constellation does not.
view=plan([1,2,3,4,5,6,7,8,9,10,11,12].map(n=>pet(n,0,'실'+n)));
check('two chips', {def:view.def, switcher:view.switcher, current:view.current},
  {def:'카시오페이아', switcher:['북두칠성','카시오페이아'], current:'오리온'});
if(process.exitCode) process.exit(process.exitCode);
console.log('constellation cases ok');
'''


class ConstellationView(unittest.TestCase):
    def test_switcher_matches_the_page_source(self):
        src = groups_source()
        self.assertIn("filter(p=>!p.example)", src)
        self.assertNotIn("${full?c.l.map", HTML)
        self.assertIn("c.l.map(([a,b])=>`<line", HTML)
        self.assertNotIn("별길은 따뜻하니", HTML)
        self.assertIn("style:'walk'", HTML)
        self.assertIn("이 파일은 아이 사진으로 만든 영상이 아니에요. 재생하지 않습니다.", HTML)
        self.assertIn("j.generated===false", HTML)
        self.assertNotIn("샘플 영상입니다. 실제 AI 생성이 아니에요.", HTML)
        self.assertNotIn("이 영상은 AI가 상상으로 만든 장면이에요", HTML)
        self.assertIn("endsWith('tossmini.com')", HTML)
        self.assertIn("https://dasi-mannal-byeol.onrender.com", HTML)
        self.assertIn("#/notes", HTML)
        self.assertIn("2026.11.08", HTML)
        self.assertNotIn("정상화 완료", HTML)
        self.assertNotIn("Pillow", HTML)
        self.assertNotIn("XAI_", HTML)
        self.assertIn("groups.slice(0,done)", HTML)
        self.assertIn('지금 별자리로', HTML)
        self.assertNotIn('#/constellation', HTML)
        completed = subprocess.run(
            ['node', '-e', CASES, src],
            check=False, text=True, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn('constellation cases ok', completed.stdout)

    def test_button_is_the_constellation_name_inside_the_plaza(self):
        draw = HTML.split('function draw', 1)[1].split('function mini', 1)[0]
        self.assertIn('class="pzdone"', draw)
        self.assertIn('class="mini', draw)
        self.assertIn('${G.c.t}', draw)
        self.assertIn("done?", draw)
        self.assertIn('.plaza .pzdone{position:absolute;left:8px;right:8px;top:8px;', HTML)

    def test_web_bundle_is_the_same_page(self):
        import tempfile
        dest = pathlib.Path(tempfile.mkstemp(suffix='.zip')[1])
        subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_web_bundle.py'), str(dest)], check=True)
        with zipfile.ZipFile(dest) as z:
            self.assertEqual(z.namelist(), ['index.html'])
            packed = z.read('index.html').decode('utf-8')
        self.assertEqual(packed, HTML)
        dest.unlink()


if __name__ == '__main__':
    unittest.main()
