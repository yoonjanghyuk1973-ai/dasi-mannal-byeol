import http.server, json, sqlite3, os, base64, uuid, re, time
from urllib.parse import urlparse
D=os.path.dirname(os.path.abspath(__file__)); DB=os.environ.get('MEMORIAL_DB') or os.path.join(D,'memorial.db')
SB=os.environ.get('SUPABASE_URL','').rstrip('/'); SBK=os.environ.get('SUPABASE_SERVICE_KEY',''); PGURL=bool(SB and SBK)
RPC_TIMEOUT=float(os.environ.get('DB_TIMEOUT','12'))
class Row(dict):
    def __init__(s,cols,vals): super().__init__(zip(cols,vals)); s._v=list(vals)
    def __getitem__(s,k): return s._v[k] if isinstance(k,int) else dict.__getitem__(s,k)
    def __iter__(s): return iter(s._v)
    def keys(s): return dict.keys(s)
class PCur:
    def __init__(s,cur,rid=None): s.c=cur; s.lastrowid=rid
    def _r(s,t): return None if t is None else Row([d.name for d in s.c.description],t)
    def fetchone(s): return s._r(s.c.fetchone()) if s.c.description else None
    def fetchall(s): return [s._r(t) for t in s.c.fetchall()] if s.c.description else []
    def __iter__(s): return iter(s.fetchall())
def _lit(v):
    if v is None: return 'NULL'
    if isinstance(v,bool): return '1' if v else '0'
    if isinstance(v,(int,float)): return repr(v)
    return "'"+str(v).replace("\x00","").replace("'","''")+"'"
def _rpc(q):
    import urllib.request, urllib.error
    r=urllib.request.Request(SB+'/rest/v1/rpc/exec_sql',json.dumps({'q':q}).encode(),{'Authorization':'Bearer '+SBK,'apikey':SBK,'Content-Type':'application/json'})
    try: return json.loads(urllib.request.urlopen(r,timeout=RPC_TIMEOUT).read() or b'null')
    except urllib.error.HTTPError as e: raise Exception('db: '+e.read().decode()[:300])
    except Exception: raise Exception('db unavailable')
class PCur:
    def __init__(s,rows,rid=None): s.rows=[Row(list(x.keys()),list(x.values())) for x in (rows or [])]; s.lastrowid=rid
    def fetchone(s): return s.rows[0] if s.rows else None
    def fetchall(s): return s.rows
    def __iter__(s): return iter(s.rows)
class PConn:
    def execute(s,q,a=()):
        parts=q.split('?'); a=list(a)
        if len(parts)-1!=len(a): raise Exception('param count')
        q=parts[0]+''.join(_lit(v)+t for v,t in zip(a,parts[1:]))
        if q.lstrip().lower().startswith('insert') and ' returning ' not in q.lower():
            r=_rpc(q+' returning id'); return PCur(r,r[0]['id'] if r else None)
        return PCur(_rpc(q))
    def executescript(s,q):
        for st in q.split(';'):
            if st.strip(): _rpc(st)
    def __enter__(s): return s
    def __exit__(s,*e): pass
def db():
    if PGURL: return PConn()
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
PK='bigserial primary key' if PGURL else 'integer primary key'
SCHEMA=f"""create table if not exists pets(id {PK},name text,species text,birth text,passed text,photo text,letter text,owner text,candles integer default 0,example integer default 0,created double precision,ekey text,visibility text default 'public');
    create table if not exists videos(id {PK},pet_id int,status text,provider text,url text,sample integer default 0,error text,job text,created double precision,style text default 'walk',src text,preview text,orig text);
    create table if not exists comments(id {PK},pet_id int,author text,body text,created double precision);
    create table if not exists posts(id {PK},kind text,pet_id int,nick text,body text,photo text,need integer default 0,r1 integer default 0,r2 integer default 0,reports integer default 0,hidden integer default 0,example integer default 0,created double precision);
    create table if not exists replies(id {PK},post_id int,nick text,body text,created double precision);
    create table if not exists events(id {PK},pet_id int,name text,created double precision);
    create table if not exists gen_log(id {PK},day text,ip text,cid text,pet_id int,created double precision)"""
# --- Supabase Storage (영구 파일 저장) ---
def sb_req(method,path,data=None,ctype='application/json'):
    import urllib.request
    r=urllib.request.Request(SB+path,data=data,method=method,headers={'Authorization':'Bearer '+SBK,'apikey':SBK,'Content-Type':ctype,'x-upsert':'true'})
    return urllib.request.urlopen(r,timeout=120).read()
def bucket_of(rel): return 'orig' if rel.startswith('orig/') else 'media'
def store_put(rel):  # rel like 'uploads/x.jpg' -> upload local file
    if not SB: return
    import mimetypes
    sb_req('POST',f'/storage/v1/object/{bucket_of(rel)}/{rel}',open(os.path.join(D,rel),'rb').read(),mimetypes.guess_type(rel)[0] or 'application/octet-stream')
def ensure_local(rel):
    rel=rel.lstrip('/'); fp=os.path.join(D,rel)
    if rel and not os.path.isfile(fp) and SB and not rel.startswith('static/'):
        try:
            b=sb_req('GET',f'/storage/v1/object/authenticated/{bucket_of(rel)}/{rel}'); os.makedirs(os.path.dirname(fp),exist_ok=True); open(fp,'wb').write(b)
        except Exception as e: print('storage get fail',rel,e,flush=True)
    return fp
for _d in ('uploads','videos','orig'): os.makedirs(os.path.join(D,_d),exist_ok=True)
def boot_storage():
    if not SB: return
    for _b,_pub in (('media',True),('orig',False)):
        try: sb_req('POST','/storage/v1/bucket',json.dumps({'id':_b,'name':_b,'public':_pub}).encode())
        except Exception: print('storage boot fail',_b,flush=True)
def save_photo(data):
    if not data: return ''
    m=re.match(r'data:image/(\w+);base64,(.*)',data,re.S)
    if not m: return ''
    ext=m.group(1).replace('jpeg','jpg'); raw=base64.b64decode(m.group(2))
    if len(raw)>8_000_000: return ''
    fn=uuid.uuid4().hex+'.'+ext; open(os.path.join(D,'uploads',fn),'wb').write(raw); store_put('uploads/'+fn); return '/uploads/'+fn
def seed_pets(c):
    if c.execute('select count(*) from pets').fetchone()[0]: return
    now=time.time()
    for n,sp,b,ps,ph,lt,ow,cd in [('[예시] 콩이','강아지','2012-03-14','2025-09-02','kongi','콩이야, 산책길마다 네 발자국이 생각나. 별에서는 마음껏 뛰어놀아.','콩이 누나',27),
        ('[예시] 나비','고양이','2010-06-01','2025-05-20','nabi','나비야, 아침 햇살 자리는 아직 네 자리야. 고마웠어.','집사',19),
        ('[예시] 솜이','토끼','2018-04-10','2025-11-30','somi','솜이야, 작은 몸으로 큰 행복을 줘서 고마워.','엄마',12),
        ('[예시] 두부','강아지','2011-01-22','2026-02-14','dubu','두부야, 꼬리 흔들며 반겨주던 현관이 아직 따뜻해.','두부 아빠',15),
        ('[예시] 미미','고양이','2013-08-08','2026-06-03','mimi','미미야, 골골송이 그리운 밤이야. 별에서 편히 쉬어.','미미 언니',9),
        ('[예시] 보리','강아지','2009-10-05','2025-12-24','bori','보리야, 함께한 16년 모두 선물이었어.','보리네 가족',22)]:
        pid=c.execute('insert into pets(name,species,birth,passed,photo,letter,owner,candles,example,created) values(?,?,?,?,?,?,?,?,1,?)',(n,sp,b,ps,'/static/samples/pet_'+ph+'.jpg',lt,ow,cd,now)).lastrowid
        for a,t in [('[예시] 별지기','좋은 곳에서 편히 쉬렴 🌟'),('[예시] 지나가던 집사','따뜻한 기억 나눠주셔서 고마워요 🤍')]:
            c.execute('insert into comments(pet_id,author,body,created) values(?,?,?,?)',(pid,a,t,now-600))
import threading, shutil, urllib.request, urllib.error, io
PROMPTS={'walk':("Animate this exact photo as the first frame. Keep the original background, lighting, framing and the pet's exact "
 "appearance (breed, fur color, markings, face) unchanged. The pet walks naturally a few steps in this same place, "
 "on the ground already visible in the photo. Do not replace the background, do not change the pet into a different animal, "
 "and do not turn the photo into a slideshow. Natural, realistic motion, about 10 seconds."),
 'play':("Animate this exact photo as the first frame. Keep the original background, lighting, framing and the pet's exact "
 "appearance (breed, fur color, markings, face) unchanged. The pet comes alive in this same place: playing, running around, "
 "wagging its tail happily. The owner's hands and arms gently enter the frame to play with and pet it, and at the end the owner "
 "hugs the pet warmly. Natural, realistic motion, warm healing mood, vertical 9:16, about 10 seconds.")}
class DemoProvider:
    name='demo'; sample=1
    def generate(s,photo_path,prompt):
        raise Exception('영상 생성 설정이 없어 아이 사진으로 영상을 만들지 않습니다')
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
        # 원본 비율을 유지한다. 이미지-영상은 입력 사진 비율을 따르므로 9:16으로 잘라 배경을 버리지 않는다.
        from PIL import Image
        im=Image.open(path).convert('RGB')
        im.thumbnail((1080,1920))
        bio=io.BytesIO(); im.save(bio,'JPEG',quality=90)
        return 'data:image/jpeg;base64,'+base64.b64encode(bio.getvalue()).decode()
    def generate(s,photo_path,prompt):
        body={'model':s.MODEL,'prompt':prompt,'duration':s.DUR,'resolution':s.RES,'aspect_ratio':'9:16'}
        if photo_path and os.path.isfile(photo_path): body['image']={'url':s._image(photo_path)}
        if os.environ.get('XAI_MOCK'):
            raise Exception('mock은 사용자 영상을 만들지 않습니다')
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
        ph=ensure_local(src) if src else ''
        fn=pv.generate(ph,PROMPTS[style]); pf='prev_'+fn
        watermark(os.path.join(D,'orig',fn),os.path.join(D,'videos',pf),pet.get('name','')); store_put('videos/'+pf); store_put('orig/'+fn)
        with db() as c: c.execute("update videos set status='done',url=?,preview=?,orig=?,job=? where id=?",('/videos/'+pf,'/videos/'+pf,fn,json.dumps({'cost_usd':(getattr(pv,'last_cost',0) or 0)/1e10}),vid))
        if not src and not pet.get('photo'): photo_from_video(pet['id'],fn,'/videos/'+pf)
        print('video',vid,'done',pv.name,getattr(pv,'last_cost',None),flush=True)
    except Exception as e:
        with db() as c:
            c.execute("update videos set status='error',error=? where id=?",(str(e)[:200],vid))
            c.execute('delete from gen_log where id=(select max(id) from gen_log where pet_id=?)',(pet['id'],))  # 실패 시 무료 횟수 돌려주기
def seed_posts(c):
    if c.execute('select count(*) from posts').fetchone()[0]: return
    now=time.time()
    for k,pid,n,b,need,ph in [('comfort',None,'[예시] 콩이엄마','어제 콩이 산책 시간이 되니까 저절로 현관을 보게 되더라고요. 다들 이런 순간 어떻게 버티셨나요?',1,''),
        ('comfort',None,'[예시] 별지기','무지개다리 건넌 아이들은 아프지 않은 곳에서 우리를 기다린대요. 오늘 하루도 잘 버틴 당신, 정말 잘하고 있어요.',0,''),
        ('memory',2,'[예시] 집사','나비는 매일 아침 창가 햇살 자리에서 꼬리를 살랑였어요. 그 자리는 아직 비워두었어요.',0,(c.execute('select photo from pets where id=2').fetchone() or [''])[0])]:
        c.execute('insert into posts(kind,pet_id,nick,body,need,photo,example,created,r1,r2) values(?,?,?,?,?,?,1,?,3,5)',(k,pid,n,b,need,ph,now-3600))
    c.execute('insert into replies(post_id,nick,body,created) values(1,?,?,?)',('[예시] 별지기','저도 그랬어요. 천천히 슬퍼해도 괜찮아요 🤍',now-1800))
import secrets, zipfile, io, subprocess
def fill_ekeys(c):
    for (i,) in c.execute('select id from pets where ekey is null').fetchall(): c.execute('update pets set ekey=? where id=?',(secrets.token_urlsafe(12),i))
def _pick_font():  # 한글 폰트: 번들 → noto-cjk 백업. 없거나 깨졌으면 크게 로그
    cands=[os.path.join(os.path.dirname(os.path.abspath(__file__)),'fonts','GothicA1-Regular.ttf'),
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc']
    for f in cands:
        try:
            if os.path.getsize(f)>100000 and open(f,'rb').read(4) in (b'\x00\x01\x00\x00',b'OTTO',b'ttcf',b'true'):
                print('KOREAN FONT OK:',f,os.path.getsize(f),flush=True); return f
            print('!!!!! KOREAN FONT INVALID (LFS pointer/corrupt?):',f,flush=True)
        except OSError: print('!!!!! KOREAN FONT MISSING:',f,flush=True)
    print('!!!!!!!!!! NO KOREAN FONT FOUND — 영상 한글이 □□□ 로 나옵니다 !!!!!!!!!!',flush=True); return cands[0]
FONT=_pick_font()
def watermark(src,dst,name=''):
    vf=("scale=360:-2,drawtext=fontfile='%s':text='다시만날별 미리보기':fontcolor=white@0.55:fontsize=22:x=(w-tw)/2:y=h*0.12,"
        "drawtext=fontfile='%s':text='PREVIEW':fontcolor=white@0.35:fontsize=46:x=(w-tw)/2:y=(h-th)/2")%(FONT,FONT)
    nm=re.sub(r'^\[예시\]\s*','',name or '').strip()[:20]
    if nm:  # 아이 이름(한글) 자막 — 특수문자 이스케이프 문제를 피하려고 textfile 사용
        tf=dst+'.txt'; open(tf,'w',encoding='utf-8').write(nm+'와 함께 걷는 별길' if (ord(nm[-1])-0xAC00)%28==0 and '가'<=nm[-1]<='힣' else nm+'과 함께 걷는 별길')
        vf+=",drawtext=fontfile='%s':textfile='%s':fontcolor=white@0.9:fontsize=24:borderw=2:bordercolor=black@0.4:x=(w-tw)/2:y=h*0.84"%(FONT,tf)
    r=subprocess.run(['ffmpeg','-y','-loglevel','error','-i',src,'-vf',vf,'-c:v','libx264','-crf','30','-preset','veryfast','-c:a','aac','-b:a','64k',dst],capture_output=True)
    if nm:
        try: os.remove(tf)
        except OSError: pass
    if r.returncode: raise Exception('워터마크 실패: '+r.stderr.decode()[-200:])
def rewatermark(vid_row,name):  # 저장된 원본(orig)에 오버레이만 다시 입힘 (AI 재생성 없음, 새 파일명으로 캐시 회피)
    src=ensure_local('orig/'+vid_row['orig'])
    if not os.path.isfile(src) or not os.path.getsize(src): raise Exception('원본 없음')
    pf='prev_'+uuid.uuid4().hex[:6]+'_'+vid_row['orig']
    watermark(src,os.path.join(D,'videos',pf),name); store_put('videos/'+pf)
    with db() as c: c.execute('update videos set url=?,preview=? where id=?',('/videos/'+pf,'/videos/'+pf,vid_row['id']))
    return '/videos/'+pf
def photo_from_video(pet_id,orig,preview):  # 사진 없는 별자리: 영상에서 프레임 추출해 대표사진으로
    try:
        src=ensure_local('orig/'+orig) if orig else ''
        crop='crop=iw:iw:0:(ih-iw)/2,scale=480:480'
        if not (src and os.path.isfile(src) and os.path.getsize(src)>0):
            src=ensure_local(preview) if preview else ''
            crop='crop=iw:ih*0.3:0:ih*0.53,scale=480:-2'  # 워터마크(상단/중앙 PREVIEW/하단 자막) 피한 영역
        if not (src and os.path.isfile(src)): return ''
        fn=uuid.uuid4().hex+'.jpg'; out=os.path.join(D,'uploads',fn)
        r=subprocess.run(['ffmpeg','-y','-loglevel','error','-ss','1','-i',src,'-frames:v','1','-vf',crop,'-q:v','3',out],capture_output=True)
        if r.returncode or not os.path.isfile(out): print('frame fail',pet_id,r.stderr[-200:],flush=True); return ''
        store_put('uploads/'+fn)
        with db() as c: c.execute("update pets set photo=? where id=? and coalesce(photo,'')=''",('/uploads/'+fn,pet_id))
        print('pet',pet_id,'photo from video',fn,flush=True); return '/uploads/'+fn
    except Exception as e: print('photo_from_video fail',pet_id,e,flush=True); return ''
def backfill_photos():
    if not DB_READY.is_set(): return
    with db() as c: rows=c.execute("select id from pets where coalesce(photo,'')='' and coalesce(example,0)=0").fetchall()
    for r in rows:
        with db() as c: v=c.execute("select src,orig,preview from videos where pet_id=? and status='done' order by id desc limit 1",(r[0],)).fetchone()
        if not v: continue
        if v[0]:
            with db() as c: c.execute('update pets set photo=? where id=?',(v[0],r[0]))
        else: photo_from_video(r[0],v[1],v[2])
DB_READY=threading.Event(); _SIDE_STARTED=False
def boot_db():
    with db() as c:
        c.executescript(SCHEMA)
        if PGURL:
            for _t in ('pets','videos','comments','posts','replies','events','gen_log'): c.execute(f'alter table {_t} enable row level security')
    with db() as c: seed_pets(c)
    with db() as c: seed_posts(c)
    with db() as c: fill_ekeys(c)
def boot():
    # Schema and storage calls hit the network in production. They must not run before the port opens.
    global _SIDE_STARTED
    if not DB_READY.is_set():
        boot_db(); DB_READY.set()
    if _SIDE_STARTED: return
    _SIDE_STARTED=True
    threading.Thread(target=boot_storage,daemon=True).start()
    threading.Thread(target=backfill_photos,daemon=True).start()
FREE_GEN=1  # 별자리당 무료 미리보기 1회
DAILY_CAP=int(os.environ.get('FREE_DAILY_CAP','30'))  # 전체 하루 무료 생성 상한
PAID_PRICE=3900  # 원본(grok-imagine-video-1.5, 720p) — 결제 미연동
BAD=['씨발','시발','병신','개새','좆','미친놈','꺼져','죽어','ㅅㅂ','ㅂㅅ']
def bad(t): return any(w in t.replace(' ','') for w in BAD)
PRES={}
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s,*a,**k): super().__init__(*a,directory=D,**k)
    # 앱인토스 미니앱(토스 WebView)에서 API를 부를 수 있도록 CORS 허용 (SDK 3.1+ / 3.0.x 도메인)
    CORS_OK={'https://dasi-mannal-byeol.apps.tossmini.com','https://dasi-mannal-byeol.private-apps.tossmini.com',
             'https://dasi-mannal-byeol.web.tossmini.com','https://dasi-mannal-byeol.private-web.tossmini.com'}
    def end_headers(s):
        o=s.headers.get('Origin','') if hasattr(s,'headers') and s.headers else ''
        if o in s.CORS_OK:
            s.send_header('Access-Control-Allow-Origin',o); s.send_header('Vary','Origin')
            s.send_header('Access-Control-Expose-Headers','Content-Disposition')
        super().end_headers()
    def do_OPTIONS(s):
        o=s.headers.get('Origin','')
        s.send_response(204 if o in s.CORS_OK else 403)
        if o in s.CORS_OK:
            s.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
            s.send_header('Access-Control-Allow-Headers','Content-Type, X-Edit-Key, X-Admin-Token')
            s.send_header('Access-Control-Max-Age','86400')
        s.send_header('Content-Length','0'); s.end_headers()
    def js(s,o,code=200):
        b=json.dumps(o,ensure_ascii=False).encode(); s.send_response(code)
        s.send_header('Content-Type','application/json; charset=utf-8'); s.send_header('Cache-Control','no-store'); s.send_header('Content-Length',len(b)); s.end_headers(); s.wfile.write(b)
    def key(s):
        from urllib.parse import parse_qs
        return s.headers.get('X-Edit-Key') or (parse_qs(urlparse(s.path).query).get('key') or [''])[0]
    def pet(s,c,i): return c.execute('select * from pets where id=?',(i,)).fetchone()
    def can_view(s,r): return r and (r['visibility']!='private' or secrets.compare_digest(s.key() or '-',r['ekey']))
    def body(s):
        n=int(s.headers.get('Content-Length',0)); return json.loads(s.rfile.read(n) or b'{}')
    def api_fail(s):
        try: return s.js({'error':'데이터를 불러오지 못했어요. 잠시 후 다시 시도해 주세요'},503)
        except Exception: return
    def admin_summary(s):
        tok=os.environ.get('ADMIN_TOKEN','')
        given=s.headers.get('X-Admin-Token') or ''
        if not tok or not given or not secrets.compare_digest(given, tok): return s.js({'error':'forbidden'},403)
        if not DB_READY.is_set(): return s.js({'error':'별자리 데이터를 아직 불러오지 못했어요. 잠시 후 다시 시도해 주세요','db':False},503)
        now=time.time()
        with db() as c:
            r=c.execute("""select
                coalesce(sum(case when coalesce(example,0)=0 then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)!=0 then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)=0 and created>=? then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)=0 and created>=? then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)=0 and coalesce(visibility,'public')='public' then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)=0 and visibility='link' then 1 else 0 end),0),
                coalesce(sum(case when coalesce(example,0)=0 and visibility='private' then 1 else 0 end),0),
                max(case when coalesce(example,0)=0 then created end)
                from pets""",(now-86400,now-7*86400)).fetchone()
        num=lambda v: int(v or 0)
        return s.js({'real_total':num(r[0]),'example_total':num(r[1]),'real_new_24h':num(r[2]),'real_new_7d':num(r[3]),
            'real_public':num(r[4]),'real_link':num(r[5]),'real_private':num(r[6]),'newest_real_created':r[7],
            'public_list_includes':'public','server_time':now})
    def do_GET(s):
        p=urlparse(s.path).path
        try: return s._do_GET()
        except Exception:
            print('api get fail',p,flush=True)
            if p.startswith('/api/'): return s.api_fail()
            raise
    def _do_GET(s):
        p=urlparse(s.path).path
        if p=='/api/health': return s.js({'ok':True,'db':DB_READY.is_set()})
        if p=='/api/admin/summary': return s.admin_summary()
        if p.startswith('/api/') and not DB_READY.is_set(): return s.js({'error':'별자리 데이터를 아직 불러오지 못했어요. 잠시 후 다시 시도해 주세요','db':False},503)
        if p=='/api/pets':
            with db() as c: return s.js([dict(r) for r in c.execute('select id,name,species,birth,passed,photo,candles,example from pets where coalesce(visibility,\'public\')=\'public\' order by example, id desc')])
        m=re.match(r'/api/pets/(\d+)$',p)
        if m:
            with db() as c:
                r=c.execute('select * from pets where id=?',(m[1],)).fetchone()
                if not r: return s.js({'error':'없음'},404)
                if not s.can_view(r): return s.js({'error':'비공개 별자리예요','private':1},403)
                o=dict(r); o['is_owner']=bool(s.key()) and secrets.compare_digest(s.key(),r['ekey']); o.pop('ekey')
                o['gen_left']=0 if o.get('example') else max(0,FREE_GEN-c.execute("select count(*) from videos where pet_id=? and status!='error' and (preview is not null or status='running')",(m[1],)).fetchone()[0]); o['videos']=[dict(x) for x in c.execute("select * from videos where pet_id=? and status='done' order by id desc",(m[1],))]; o['comments']=[dict(x) for x in c.execute('select * from comments where pet_id=? order by id desc',(m[1],))]
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
                fp=ensure_local(path) if path else ''
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
        if p.startswith('/videos/') or p.startswith('/uploads/'):
            if SB and not os.path.isfile(os.path.join(D,p.lstrip('/'))):
                s.send_response(302); s.send_header('Location',f'{SB}/storage/v1/object/public/media{p}'); s.send_header('Cache-Control','public, max-age=86400'); s.end_headers(); return
            return super().do_GET()
        if p.startswith('/static/'): return super().do_GET()
        s.path='/static/index.html'; return super().do_GET()
    def do_POST(s):
        p=urlparse(s.path).path
        if p.startswith('/api/') and not DB_READY.is_set(): return s.js({'error':'별자리 데이터를 아직 불러오지 못했어요. 잠시 후 다시 시도해 주세요','db':False},503)
        try: return s._do_POST()
        except Exception:
            print('api post fail',p,flush=True)
            return s.api_fail()
    def _do_POST(s):
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
        m=re.match(r'/api/admin/rewatermark/(\d+)$',p)  # 관리자 전용: ADMIN_TOKEN 헤더 필요
        if m:
            tok=os.environ.get('ADMIN_TOKEN','')
            if not tok or not secrets.compare_digest(s.headers.get('X-Admin-Token',''),tok): return s.js({'error':'forbidden'},403)
            with db() as c:
                pet=s.pet(c,m[1]); v=c.execute("select * from videos where pet_id=? and status='done' and orig is not null order by id desc limit 1",(m[1],)).fetchone()
            if not pet or not v: return s.js({'error':'no video'},404)
            try: return s.js({'ok':1,'url':rewatermark(dict(v),pet['name'])})
            except Exception as e: return s.js({'error':str(e)[:300]},500)
        m=re.match(r'/api/pets/(\d+)/videos$',p)
        if m:
            with db() as c:
                pet=c.execute('select * from pets where id=?',(m[1],)).fetchone()
                if not pet: return s.js({'error':'없음'},404)
                if not s.can_view(pet): return s.js({'error':'비공개 별자리예요'},403)
                if pet['example']: return s.js({'error':'예시 별자리는 영상을 만들 수 없어요. 내 아이 별자리를 만들어 주세요 🐾'},403)
                style=b.get('style') if b.get('style') in PROMPTS else 'play'
                exist=c.execute("select id,status,provider,sample,style from videos where pet_id=? and style=? and status!='error' and coalesce(sample,0)=0 order by id desc limit 1",(m[1],style)).fetchone()
                if exist: return s.js({'id':exist['id'],'provider':exist['provider'],'sample':0,'style':exist['style'],'status':exist['status'],'reused':1,'generated':True})
                if not os.environ.get('XAI_API_KEY') or os.environ.get('XAI_MOCK'):
                    return s.js({'error':'이 서버 프로세스에서는 아이 사진으로 산책 영상을 만들지 못했습니다. 샘플 영상은 재생하지 않아요.','provider':'unavailable','generated':False},503)
                if c.execute("select count(*) from videos where pet_id=? and status!='error' and (preview is not null or status='running')",(m[1],)).fetchone()[0]>=FREE_GEN: return s.js({'error':'이 별자리의 무료 미리보기를 이미 사용했어요'},402)
                day=time.strftime('%Y-%m-%d'); ip=(s.headers.get('X-Forwarded-For') or s.client_address[0]).split(',')[0].strip(); cid=str(b.get('cid') or '')[:40]
                if c.execute('select count(*) from gen_log where day=? and (ip=? or (length(cid)>0 and cid=?))',(day,ip,cid)).fetchone()[0]>=1: return s.js({'error':'무료 미리보기는 하루에 한 번만 만들 수 있어요. 내일 다시 찾아와 주세요 🌙'},429)
                if c.execute('select count(*) from gen_log where day=?',(day,)).fetchone()[0]>=DAILY_CAP: return s.js({'error':'오늘 준비된 무료 미리보기가 모두 소진됐어요. 내일 다시 시도해 주세요 🌙'},429)
                c.execute('insert into gen_log(day,ip,cid,pet_id,created) values(?,?,?,?,?)',(day,ip,cid,m[1],time.time()))
                src=save_photo(b.get('photo')) or pet['photo'] or ''
                pv=provider(); sample=1 if pv.name=='demo' or os.environ.get('XAI_MOCK') else pv.sample
                cur=c.execute("insert into videos(pet_id,status,provider,sample,created,style,src) values(?,?,?,?,?,?,?)",(m[1],'running',pv.name,sample,time.time(),style,src))
                vid=cur.lastrowid
                if src and not pet['photo']: c.execute('update pets set photo=? where id=?',(src,m[1]))  # 별자리 별에 실제 사진 표시
            threading.Thread(target=run_job,args=(vid,dict(pet),style,src),daemon=True).start()
            return s.js({'id':vid,'provider':pv.name,'sample':sample,'style':style,'status':'running'})
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
def main():
    def safe():
        delay=1
        while not DB_READY.is_set():
            try: boot()
            except Exception:
                print('db boot fail',flush=True); time.sleep(delay); delay=min(delay*2,30)
    threading.Thread(target=safe,name='boot',daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT',8787))),H).serve_forever()
if __name__=='__main__': main()
