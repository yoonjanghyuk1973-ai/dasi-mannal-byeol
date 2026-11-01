import http.server, json, sqlite3, os, base64, uuid, re, time
from urllib.parse import urlparse
D=os.path.dirname(os.path.abspath(__file__)); DB=os.environ.get('MEMORIAL_DB') or os.path.join(D,'memorial.db')
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with db() as c:
    c.executescript("""create table if not exists pets(id integer primary key,name text,species text,birth text,passed text,photo text,letter text,owner text,candles integer default 0,example integer default 0,created real);
    create table if not exists videos(id integer primary key,pet_id int,status text,provider text,url text,sample integer default 0,error text,job text,created real);
    create table if not exists _x(i int);
    create table if not exists comments(id integer primary key,pet_id int,author text,body text,created real);""")
def save_photo(data):
    if not data: return ''
    m=re.match(r'data:image/(\w+);base64,(.*)',data,re.S)
    if not m: return ''
    ext=m.group(1).replace('jpeg','jpg'); raw=base64.b64decode(m.group(2))
    if len(raw)>8_000_000: return ''
    fn=uuid.uuid4().hex+'.'+ext; open(os.path.join(D,'uploads',fn),'wb').write(raw); return '/uploads/'+fn
import threading, shutil, urllib.request, urllib.error, io
PROMPT=("Vertical 9:16 dreamy night scene, about 10 seconds. The pet from the photo walks happily beside its owner "
 "along a softly glowing path of golden stars across a night sky, gentle sparkles and moonlight, warm and peaceful. "
 "At the end the owner kneels and hugs the pet tenderly. Soft cinematic, healing mood.")
PROMPTS={'walk':PROMPT,'play':("Animate this exact photo as the first frame. Keep the original background, lighting, framing and the pet's exact "
 "appearance (breed, fur color, markings, face) unchanged. The pet comes alive in this same place: playing, running around, "
 "wagging its tail happily. The owner's hands and arms gently enter the frame to play with and pet it, and at the end the owner "
 "hugs the pet warmly. Natural, realistic motion, warm healing mood, vertical 9:16, about 10 seconds.")}
try:
    with db() as c: c.execute("alter table videos add column style text default 'walk'"); c.execute("alter table videos add column src text")
except Exception: pass
class DemoProvider:
    name='demo'; sample=1
    def generate(s,photo_path,prompt):
        time.sleep(6)  # 생성 대기 시뮬레이션
        fn='sample_'+uuid.uuid4().hex[:8]+'.mp4'
        shutil.copy(os.path.join(D,'static','samples','sample_walk.mp4'),os.path.join(D,'orig',fn)); return fn
class XaiProvider:
    # xAI Grok Imagine image-to-video (docs.x.ai): POST /v1/videos/generations -> {request_id}; GET /v1/videos/{id} -> status pending|done|failed|expired, video.url, usage.cost_in_usd_ticks
    name='xai'; sample=0
    DUR=int(os.environ.get('XAI_VIDEO_DUR','10'))
    def __init__(s,key,model='grok-imagine-video-1.5-lite',res='480p'): s.key=key; s.MODEL=model; s.RES=res
    def _req(s,url,data=None):
        r=urllib.request.Request(url,data=json.dumps(data).encode() if data else None,headers={'Authorization':'Bearer '+s.key,'Content-Type':'application/json','User-Agent':'dasimannalbyeol/1.0'})
        try: return json.load(urllib.request.urlopen(r,timeout=60))
        except urllib.error.HTTPError as e: raise Exception(f'xAI {e.code}: '+e.read().decode()[:300])
    def _image(s,path):
        # 출력 비율은 입력 사진 비율을 따름 -> 9:16 세로로 가운데 자르기
        from PIL import Image
        im=Image.open(path).convert('RGB'); w,h=im.size; t=9/16
        if w/h>t: nw=int(h*t); im=im.crop(((w-nw)//2,0,(w-nw)//2+nw,h))
        elif w/h<t-0.01: nh=int(w/t); im=im.crop((0,(h-nh)//2,w,(h-nh)//2+nh))
        im.thumbnail((1080,1920)); bio=io.BytesIO(); im.save(bio,'JPEG',quality=90)
        return 'data:image/jpeg;base64,'+base64.b64encode(bio.getvalue()).decode()
    def generate(s,photo_path,prompt):
        body={'model':s.MODEL,'prompt':prompt,'duration':s.DUR,'resolution':s.RES,'aspect_ratio':'9:16'}
        if photo_path and os.path.isfile(photo_path): body['image']={'url':s._image(photo_path)}
        if os.environ.get('XAI_MOCK'):
            print('MOCK xai request',json.dumps({k:v for k,v in body.items() if k!='image'}),'image' in body,flush=True)
            fn='mock_'+uuid.uuid4().hex[:8]+'.mp4'; shutil.copy(os.path.join(D,'static','samples','sample_walk.mp4'),os.path.join(D,'orig',fn)); s.last_cost=0; return fn
        rid=s._req('https://api.x.ai/v1/videos/generations',body)['request_id']
        for _ in range(180):
            time.sleep(5); r=s._req('https://api.x.ai/v1/videos/'+rid)
            st=r.get('status')
            if st=='done':
                fn='xai_'+rid+'.mp4'; q=urllib.request.Request(r['video']['url'],headers={'User-Agent':'dasimannalbyeol/1.0'})
                open(os.path.join(D,'orig',fn),'wb').write(urllib.request.urlopen(q,timeout=120).read())
                s.last_cost=(r.get('usage') or {}).get('cost_in_usd_ticks'); return fn
            if st in('failed','expired'): raise Exception('생성 실패: '+json.dumps(r,ensure_ascii=False)[:300])
        raise Exception('시간 초과')
def provider():  # 무료 미리보기: 1.5-lite 480p
    k=os.environ.get('XAI_API_KEY')
    return XaiProvider(k,'grok-imagine-video-1.5-lite','480p') if k else DemoProvider()
def paid_provider():  # 유료 원본: 1.5 720p — 결제 연동 후에만 호출할 것
    return XaiProvider(os.environ['XAI_API_KEY'],'grok-imagine-video-1.5','720p')
def run_job(vid,pet,style,src):
    pv=provider()
    try:
        ph=os.path.join(D,src.lstrip('/')) if src else ''
        fn=pv.generate(ph,PROMPTS[style]); pf='prev_'+fn
        watermark(os.path.join(D,'orig',fn),os.path.join(D,'videos',pf))
        with db() as c: c.execute("update videos set status='done',url=?,preview=?,orig=?,job=? where id=?",('/videos/'+pf,'/videos/'+pf,fn,json.dumps({'cost_usd':(getattr(pv,'last_cost',0) or 0)/1e10}),vid))
        print('video',vid,'done',pv.name,getattr(pv,'last_cost',None),flush=True)
    except Exception as e:
        with db() as c:
            c.execute("update videos set status='error',error=? where id=?",(str(e)[:200],vid))
            c.execute('delete from gen_log where id=(select max(id) from gen_log where pet_id=?)',(pet['id'],))  # 실패 시 무료 횟수 돌려주기
with db() as c:
    c.executescript('''create table if not exists posts(id integer primary key,kind text,pet_id int,nick text,body text,photo text,need integer default 0,r1 integer default 0,r2 integer default 0,reports integer default 0,hidden integer default 0,example integer default 0,created real);
    create table if not exists replies(id integer primary key,post_id int,nick text,body text,created real);
    create table if not exists events(id integer primary key,pet_id int,name text,created real);''')
    if not c.execute('select count(*) from posts').fetchone()[0]:
        now=time.time()
        for k,pid,n,b,need,ph in [('comfort',None,'[예시] 콩이엄마','어제 콩이 산책 시간이 되니까 저절로 현관을 보게 되더라고요. 다들 이런 순간 어떻게 버티셨나요?',1,''),
            ('comfort',None,'[예시] 별지기','무지개다리 건넌 아이들은 아프지 않은 곳에서 우리를 기다린대요. 오늘 하루도 잘 버틴 당신, 정말 잘하고 있어요.',0,''),
            ('memory',2,'[예시] 집사','나비는 매일 아침 창가 햇살 자리에서 꼬리를 살랑였어요. 그 자리는 아직 비워두었어요.',0,(c.execute('select photo from pets where id=2').fetchone() or [''])[0])]:
            cur=c.execute('insert into posts(kind,pet_id,nick,body,need,photo,example,created,r1,r2) values(?,?,?,?,?,?,1,?,3,5)',(k,pid,n,b,need,ph,now-3600))
        c.execute('insert into replies(post_id,nick,body,created) values(1,?,?,?)',('[예시] 별지기','저도 그랬어요. 천천히 슬퍼해도 괜찮아요 🤍',now-1800))
import secrets, zipfile, io, subprocess
for col in ["ekey text","visibility text default 'public'"]:
    try:
        with db() as c: c.execute('alter table pets add column '+col)
    except Exception: pass
for col in ["preview text","orig text"]:
    try:
        with db() as c: c.execute('alter table videos add column '+col)
    except Exception: pass
with db() as c:
    for (i,) in c.execute('select id from pets where ekey is null').fetchall(): c.execute('update pets set ekey=? where id=?',(secrets.token_urlsafe(12),i))
FONT='/usr/share/fonts/truetype/sand-box/google/Gothic A1/GothicA1-Regular.ttf'
def watermark(src,dst):
    vf=("scale=360:-2,drawtext=fontfile='%s':text='다시만날별 미리보기':fontcolor=white@0.55:fontsize=22:x=(w-tw)/2:y=h*0.12,"
        "drawtext=fontfile='%s':text='PREVIEW':fontcolor=white@0.35:fontsize=46:x=(w-tw)/2:y=(h-th)/2")%(FONT,FONT)
    r=subprocess.run(['ffmpeg','-y','-loglevel','error','-i',src,'-vf',vf,'-c:v','libx264','-crf','30','-preset','veryfast','-c:a','aac','-b:a','64k',dst],capture_output=True)
    if r.returncode: raise Exception('워터마크 실패: '+r.stderr.decode()[-200:])
FREE_GEN=1  # 별자리당 무료 미리보기 1회
DAILY_CAP=int(os.environ.get('FREE_DAILY_CAP','30'))  # 전체 하루 무료 생성 상한
PAID_PRICE=3900  # 원본(grok-imagine-video-1.5, 720p) — 결제 미연동
with db() as c: c.execute('create table if not exists gen_log(id integer primary key,day text,ip text,cid text,pet_id int,created real)')
BAD=['씨발','시발','병신','개새','좆','미친놈','꺼져','죽어','ㅅㅂ','ㅂㅅ']
def bad(t): return any(w in t.replace(' ','') for w in BAD)
PRES={}
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s,*a,**k): super().__init__(*a,directory=D,**k)
    def js(s,o,code=200):
        b=json.dumps(o,ensure_ascii=False).encode(); s.send_response(code)
        s.send_header('Content-Type','application/json; charset=utf-8'); s.send_header('Content-Length',len(b)); s.end_headers(); s.wfile.write(b)
    def key(s):
        from urllib.parse import parse_qs
        return s.headers.get('X-Edit-Key') or (parse_qs(urlparse(s.path).query).get('key') or [''])[0]
    def pet(s,c,i): return c.execute('select * from pets where id=?',(i,)).fetchone()
    def can_view(s,r): return r and (r['visibility']!='private' or secrets.compare_digest(s.key() or '-',r['ekey']))
    def body(s):
        n=int(s.headers.get('Content-Length',0)); return json.loads(s.rfile.read(n) or b'{}')
    def do_GET(s):
        p=urlparse(s.path).path
        if p=='/api/pets':
            with db() as c: return s.js([dict(r) for r in c.execute('select id,name,species,birth,passed,photo,candles,example from pets where coalesce(visibility,\'public\')=\'public\' order by example, id desc')])
        m=re.match(r'/api/pets/(\d+)$',p)
        if m:
            with db() as c:
                r=c.execute('select * from pets where id=?',(m[1],)).fetchone()
                if not r: return s.js({'error':'없음'},404)
                if not s.can_view(r): return s.js({'error':'비공개 별자리예요','private':1},403)
                o=dict(r); o['is_owner']=bool(s.key()) and secrets.compare_digest(s.key(),r['ekey']); o.pop('ekey')
                o['gen_left']=max(0,FREE_GEN-c.execute("select count(*) from videos where pet_id=? and status!='error' and (preview is not null or status='running')",(m[1],)).fetchone()[0]); o['videos']=[dict(x) for x in c.execute("select * from videos where pet_id=? and status='done' order by id desc",(m[1],))]; o['comments']=[dict(x) for x in c.execute('select * from comments where pet_id=? order by id desc',(m[1],))]
            return s.js(o)
        m=re.match(r'/api/videos/(\d+)$',p)
        if m:
            with db() as c: r=c.execute('select * from videos where id=?',(m[1],)).fetchone()
            return s.js(dict(r) if r else {'error':'없음'},200 if r else 404)
        m=re.match(r'/api/pets/(\d+)/export$',p)
        if m:
            with db() as c:
                r=s.pet(c,m[1])
                if not r or not secrets.compare_digest(s.key() or '-',r['ekey']): return s.js({'error':'관리 키가 맞지 않아요'},403)
                cm=[dict(x) for x in c.execute('select author,body,created from comments where pet_id=?',(m[1],))]
                ps=[dict(x) for x in c.execute('select nick,body,photo,created from posts where pet_id=? and kind=?',(m[1],'memory'))]
                vs=[dict(x) for x in c.execute("select url,orig from videos where pet_id=? and status='done'",(m[1],))]
            bio=io.BytesIO(); z=zipfile.ZipFile(bio,'w',zipfile.ZIP_DEFLATED)
            def add(path,arc):
                fp=os.path.join(D,path.lstrip('/'))
                if path and os.path.isfile(fp): z.write(fp,arc)
            add(r['photo'] or '','사진/대표사진'+os.path.splitext(r['photo'] or '')[1])
            z.writestr('편지.txt',f"{r['name']}에게\n{r['birth']} ~ {r['passed']}\n\n{r['letter'] or ''}\n\n— {r['owner'] or '보호자'}")
            z.writestr('방명록.txt','\n\n'.join(f"[{time.strftime('%Y-%m-%d',time.localtime(x['created']))}] {x['author']}: {x['body']}" for x in cm) or '(비어 있음)')
            z.writestr('추억.txt','\n\n'.join(f"[{time.strftime('%Y-%m-%d',time.localtime(x['created']))}] {x['nick']}: {x['body']}" for x in ps) or '(비어 있음)')
            for i,x in enumerate(ps): add(x['photo'] or '',f'사진/추억_{i+1}'+os.path.splitext(x['photo'] or '')[1])
            for i,v in enumerate(vs): add(v['url'],f'영상/영상_{i+1}_미리보기.mp4')
            z.close(); b=bio.getvalue(); s.send_response(200)
            s.send_header('Content-Type','application/zip'); s.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+__import__('urllib.parse').parse.quote(r['name']+'_다시만날별.zip')); s.send_header('Content-Length',len(b)); s.end_headers(); return s.wfile.write(b)
        if p=='/api/live':
            now=time.time()
            for k in [k for k,v in PRES.items() if now-v>45]: PRES.pop(k)
            with db() as c: ev=[dict(r) for r in c.execute('select * from events order by id desc limit 8')]
            return s.js({'online':max(1,len(PRES)),'events':ev,'now':now})
        if p=='/api/posts':
            from urllib.parse import parse_qs
            q=parse_qs(urlparse(s.path).query); kind=(q.get('kind') or ['comfort'])[0]; pid=(q.get('pet') or [None])[0]
            sql='select p.*,pets.name pet_name from posts p left join pets on pets.id=p.pet_id where kind=? and hidden=0 and (p.pet_id is null or coalesce(pets.visibility,\'public\')=\'public\' or p.pet_id=?)'; a=[kind,pid or -1]
            if pid: sql+=' and p.pet_id=?'; a.append(pid)
            if (q.get('need') or [''])[0]=='1': sql+=' and need=1'
            with db() as c:
                ps=[dict(r) for r in c.execute(sql+' order by example, p.id desc limit 100',a)]
                for x in ps: x['replies']=[dict(r) for r in c.execute('select * from replies where post_id=? order by id',(x['id'],))]
            return s.js(ps)
        if p.startswith('/videos/'): return super().do_GET()
        if p.startswith('/uploads/') or p.startswith('/static/'): return super().do_GET()
        s.path='/static/index.html'; return super().do_GET()
    def do_POST(s):
        p=urlparse(s.path).path
        try: b=s.body()
        except Exception: return s.js({'error':'잘못된 요청'},400)
        if p=='/api/pets':
            name=(b.get('name') or '').strip()[:40]
            if not name: return s.js({'error':'이름을 입력해 주세요'},400)
            with db() as c:
                k=secrets.token_urlsafe(12); vis=b.get('visibility') if b.get('visibility') in('public','link','private') else 'public'
                cur=c.execute('insert into pets(ekey,visibility,name,species,birth,passed,photo,letter,owner,created) values(?,?,?,?,?,?,?,?,?,?)',(k,vis,name,(b.get('species') or '')[:20],b.get('birth') or '',b.get('passed') or '',save_photo(b.get('photo')),(b.get('letter') or '')[:5000],(b.get('owner') or '')[:30],time.time()))
            return s.js({'id':cur.lastrowid,'key':k})
        m=re.match(r'/api/pets/(\d+)/(edit|delete|original)$',p)
        if m:
            with db() as c:
                r=s.pet(c,m[1])
                if not r or not secrets.compare_digest(s.key() or '-',r['ekey']): return s.js({'error':'관리 키가 맞지 않아요'},403)
                if m[2]=='original': return s.js({'error':'결제 기능은 아직 연결되지 않았어요 (준비 중)','payment':'not_connected','price':PAID_PRICE,'model':'grok-imagine-video-1.5','resolution':'720p'},402)
                if m[2]=='delete':
                    c.execute('delete from comments where pet_id=?',(m[1],)); c.execute('delete from posts where pet_id=?',(m[1],)); c.execute('delete from videos where pet_id=?',(m[1],)); c.execute('delete from pets where id=?',(m[1],))
                    return s.js({'ok':1})
                name=(b.get('name') or '').strip()[:40]
                if not name: return s.js({'error':'이름을 입력해 주세요'},400)
                vis=b.get('visibility') if b.get('visibility') in('public','link','private') else r['visibility']
                ph=save_photo(b.get('photo')) or r['photo']
                c.execute('update pets set name=?,species=?,birth=?,passed=?,owner=?,letter=?,photo=?,visibility=? where id=?',(name,(b.get('species') or '')[:20],b.get('birth') or '',b.get('passed') or '',(b.get('owner') or '')[:30],(b.get('letter') or '')[:5000],ph,vis,m[1]))
            return s.js({'ok':1})
        if p=='/api/heartbeat':
            PRES[str(b.get('cid'))[:40]]=time.time(); return s.js({'online':len(PRES)})
        if p=='/api/posts':
            t=(b.get('body') or '').strip()[:600]; kind=b.get('kind') if b.get('kind') in('comfort','memory') else 'comfort'
            if not t: return s.js({'error':'내용을 입력해 주세요'},400)
            if bad(t+(b.get('nick') or '')): return s.js({'error':'따뜻한 말로 다시 적어 주세요 🙏'},400)
            ph=save_photo(b.get('photo')) if kind=='memory' else ''
            pid=b.get('pet_id') or None
            if kind=='memory' and not pid: return s.js({'error':'추억을 나눌 아이를 골라 주세요'},400)
            with db() as c: cur=c.execute('insert into posts(kind,pet_id,nick,body,photo,need,created) values(?,?,?,?,?,?,?)',(kind,pid,(b.get('nick') or '').strip()[:20] or '익명',t,ph,1 if b.get('need') else 0,time.time()))
            return s.js({'id':cur.lastrowid})
        m=re.match(r'/api/posts/(\d+)/(react|reply|report)$',p)
        if m:
            with db() as c:
                if m[2]=='react':
                    col='r1' if b.get('r')=='r1' else 'r2'; c.execute(f'update posts set {col}={col}+1 where id=?',(m[1],))
                    r=c.execute('select r1,r2 from posts where id=?',(m[1],)).fetchone(); return s.js(dict(r))
                if m[2]=='report':
                    c.execute('update posts set reports=reports+1, hidden=case when reports+1>=3 then 1 else hidden end where id=?',(m[1],)); return s.js({'ok':1})
                t=(b.get('body') or '').strip()[:300]
                if not t: return s.js({'error':'내용을 입력해 주세요'},400)
                if bad(t): return s.js({'error':'따뜻한 말로 다시 적어 주세요 🙏'},400)
                c.execute('insert into replies(post_id,nick,body,created) values(?,?,?,?)',(m[1],(b.get('nick') or '').strip()[:20] or '익명',t,time.time()))
            return s.js({'ok':1})
        m=re.match(r'/api/pets/(\d+)/videos$',p)
        if m:
            with db() as c:
                pet=c.execute('select * from pets where id=?',(m[1],)).fetchone()
                if not pet: return s.js({'error':'없음'},404)
                if not s.can_view(pet): return s.js({'error':'비공개 별자리예요'},403)
                if c.execute("select count(*) from videos where pet_id=? and status!='error' and (preview is not null or status='running')",(m[1],)).fetchone()[0]>=FREE_GEN: return s.js({'error':'이 별자리의 무료 미리보기를 이미 사용했어요'},402)
                day=time.strftime('%Y-%m-%d'); ip=(s.headers.get('X-Forwarded-For') or s.client_address[0]).split(',')[0].strip(); cid=str(b.get('cid') or '')[:40]
                if c.execute('select count(*) from gen_log where day=? and (ip=? or (length(cid)>0 and cid=?))',(day,ip,cid)).fetchone()[0]>=1: return s.js({'error':'무료 미리보기는 하루에 한 번만 만들 수 있어요. 내일 다시 찾아와 주세요 🌙'},429)
                if c.execute('select count(*) from gen_log where day=?',(day,)).fetchone()[0]>=DAILY_CAP: return s.js({'error':'오늘 준비된 무료 미리보기가 모두 소진됐어요. 내일 다시 시도해 주세요 🌙'},429)
                c.execute('insert into gen_log(day,ip,cid,pet_id,created) values(?,?,?,?,?)',(day,ip,cid,m[1],time.time()))
                style=b.get('style') if b.get('style') in PROMPTS else 'play'
                src=save_photo(b.get('photo')) or pet['photo'] or ''
                pv=provider(); cur=c.execute("insert into videos(pet_id,status,provider,sample,created,style,src) values(?,?,?,?,?,?,?)",(m[1],'running',pv.name,pv.sample,time.time(),style,src))
                vid=cur.lastrowid
            threading.Thread(target=run_job,args=(vid,dict(pet),style,src),daemon=True).start()
            return s.js({'id':vid,'provider':pv.name,'sample':pv.sample,'style':style})
        m=re.match(r'/api/pets/(\d+)/(candle|comments)$',p)
        if m:
            with db() as c:
                if not s.can_view(s.pet(c,m[1])): return s.js({'error':'비공개 별자리예요'},403)
                if m[2]=='candle':
                    c.execute('update pets set candles=candles+1 where id=?',(m[1],))
                    r=c.execute('select name from pets where id=?',(m[1],)).fetchone()
                    if r: c.execute('insert into events(pet_id,name,created) values(?,?,?)',(m[1],r[0],time.time()))
                    return s.js({'candles':c.execute('select candles from pets where id=?',(m[1],)).fetchone()[0]})
                t=(b.get('body') or '').strip()[:500]
                if bad(t): return s.js({'error':'따뜻한 말로 다시 적어 주세요 🙏'},400)
                if not t: return s.js({'error':'내용을 입력해 주세요'},400)
                c.execute('insert into comments(pet_id,author,body,created) values(?,?,?,?)',(m[1],(b.get('author') or '익명').strip()[:20] or '익명',t,time.time()))
            return s.js({'ok':1})
        s.js({'error':'not found'},404)
http.server.ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT',8787))),H).serve_forever()
