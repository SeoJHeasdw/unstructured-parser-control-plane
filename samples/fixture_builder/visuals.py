from pathlib import Path
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from core import NOTICE, WORK, register, evidence

FONT_FILE = Path(os.environ.get('CORPUS_KOREAN_FONT', '/System/Library/Fonts/AppleSDGothicNeo.ttc'))
FONTS = {}
INK, BLUE, MUTED, GRID, PAPER = '#233744', '#14617A', '#506976', '#CDDBDF', '#F7FAFA'
VISUAL_TEXT = {}


def font(size):
    if size not in FONTS:
        FONTS[size] = ImageFont.truetype(str(FONT_FILE), size)
    return FONTS[size]


def text(draw, xy, value, size=27, fill=INK, anchor=None):
    draw.text(xy, value, font=font(size), fill=fill, anchor=anchor)


def save(image, path, labels=()):
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        image.convert('RGB').save(path, 'JPEG', quality=85, optimize=True)
    else:
        image.save(path, optimize=True)
    VISUAL_TEXT[str(path)] = list(labels)
    return path


def graphic(title, subtitle='', dims=(1100, 620)):
    image = Image.new('RGB', dims, 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, dims[0], 10), fill=BLUE)
    text(draw, (42, 35), title, 38)
    if subtitle:
        text(draw, (44, 91), subtitle, 23, MUTED)
    text(draw, (44, dims[1]-34), NOTICE, 16, MUTED)
    return image, draw


def chart(path, title, ticks, series, *, limits=(0, 6), threshold=None, unit='mm/s'):
    image, draw = graphic(title, f'측정 단위  {unit}')
    x0, x1, y0, y1 = 125, 1025, 158, 490
    top, bottom = limits[1], limits[0]
    y = lambda v: y1 - (v-bottom)/(top-bottom)*(y1-y0)
    x = lambda i: x0 + 24 + i*(x1-x0-48)/max(1, len(ticks)-1)
    for i in range(7):
        v = bottom+(top-bottom)*i/6
        draw.line((x0,y(v),x1,y(v)), fill=GRID, width=2)
        text(draw,(x0-14,y(v)),f'{v:g}',20,MUTED,'rm')
    draw.line((x0,y0,x0,y1,x1,y1), fill=MUTED, width=2)
    for i, tick in enumerate(ticks):
        text(draw,(x(i),y1+16),tick,19,MUTED,'mt')
    if threshold is not None:
        value, label = threshold
        for px in range(x0,x1,23):
            draw.line((px,y(value),min(px+13,x1),y(value)), fill='#AF474A', width=3)
        text(draw,(x1,y(value)-8),label,21,'#95383F','rs')
    colors = ['#156F89','#B86528','#4F8064']
    for index,(label,values) in enumerate(series):
        color=colors[index]
        points=[(x(i),y(v)) for i,v in enumerate(values)]
        draw.line(points,fill=color,width=5)
        for px,py in points:
            draw.ellipse((px-6,py-6,px+6,py+6),fill=color)
        lx=128+220*index
        draw.line((lx,552,lx+35,552),fill=color,width=5)
        text(draw,(lx+46,552),label,22,INK,'lm')
    return save(image,path,[title,*ticks,unit,*[x[0] for x in series],*([threshold[1]] if threshold else [])])


def arrow(draw,start,end,fill=BLUE,width=5):
    draw.line((start,end),fill=fill,width=width)
    angle=math.atan2(end[1]-start[1],end[0]-start[0])
    arms=[(end[0]-18*math.cos(angle+s*.55),end[1]-18*math.sin(angle+s*.55)) for s in (-1,1)]
    draw.polygon([end,*arms],fill=fill)


def pid(path):
    title='냉각수 순환계통'
    image, draw = graphic(title, '제1공장 · 냉각수 순환설비 EQ-COOL-02')
    for x0,y0,x1,y1,label,desc in [
        (85,258,235,382,'TK-01','완충 탱크'),(365,164,552,252,'EQ-PUMP-P1','주 펌프'),
        (365,375,552,463,'EQ-PUMP-P2','예비 펌프'),(758,245,945,393,'HX-01','열교환기')]:
        draw.rounded_rectangle((x0,y0,x1,y1),12,fill='#E9F5F6',outline=BLUE,width=4)
        text(draw,((x0+x1)/2,(y0+y1)/2-11),label,25,INK,'mm')
        text(draw,((x0+x1)/2,(y0+y1)/2+23),desc,20,MUTED,'mm')
    for points in [[(235,320),(294,320),(294,205),(365,205)],[(294,320),(294,415),(365,415)],
                   [(552,205),(650,205),(650,290),(758,290)],[(552,415),(650,415),(650,348),(758,348)],
                   [(945,319),(999,319),(999,512),(160,512),(160,382)]]:
        draw.line(points, fill=BLUE,width=5)
        arrow(draw,points[-2],points[-1])
    text(draw,(418,495),'복귀 헤더',23)
    text(draw,(683,177),'공급 방향',23)
    return save(image,path,[title,'EQ-COOL-02','TK-01','완충 탱크','EQ-PUMP-P1','주 펌프',
                            'EQ-PUMP-P2','예비 펌프','HX-01','열교환기','복귀 헤더','공급 방향'])


def swab(path):
    title='스왑 채취 위치 배치도'
    image, d = graphic(title, '세척 검증용 탱크 · 상부에서 본 방향')
    d.ellipse((260,150,600,490),fill='#EAF4F7',outline=BLUE,width=6)
    d.ellipse((350,240,510,400),outline=GRID,width=3)
    d.line(((430,490),(430,533),(855,533),(855,210),(598,210)),fill=BLUE,width=11)
    points=[(420,285,'01 탱크 맨홀'),(455,430,'02 배출 노즐'),(730,520,'19 복귀 배관'),(846,315,'20 밸브 시트')]
    for x,y,label in points:
        d.ellipse((x-10,y-10,x+10,y+10),fill='#B65B31')
        text(d,(x+18,y-12),label,22)
    return save(image,path,[title,*[v[2] for v in points]])


def fishbone(path):
    title='냉동고 D 원인 분석도'
    image,d=graphic(title,'DEV-2026-0117 · 확인 대상과 확인 결과')
    arrow(d,(108,325),(1000,325))
    for index,(factor,detail) in enumerate([
        ('인력','인수인계 시각'),('설비','도어 패킹 들뜸'),('방법','닫힘 확인 누락'),
        ('환경','작업 동선 혼잡'),('자재','랙 돌출 여부'),('측정','경보 시각 대조')]):
        x=175+(index%3)*242
        y=170 if index<3 else 477
        arrow(d,(x,y+25 if index<3 else y-22),(x+100,325))
        text(d,(x,y),factor,31,BLUE,'mm')
        text(d,(x,y-38 if index<3 else y+39),detail,23,INK,'mm')
    text(d,(1005,288),'온도 이탈',25,INK,'rs')
    return save(image,path,[title,'도어 패킹 들뜸','닫힘 확인 누락','경보 시각 대조','온도 이탈',
                            '인력','설비','방법','환경','자재','측정','인수인계 시각','작업 동선 혼잡','랙 돌출 여부'])


def chromatogram(path):
    image,d=graphic('표준액 크로마토그램','EQ-HPLC-07 · 머무름 시간(min) / 응답(mAU)')
    coords=[]
    for i in range(900):
        v=i/100
        level=17+65*math.exp(-((v-2.14)/.22)**2)+218*math.exp(-((v-5.62)/.31)**2)+38*math.exp(-((v-7.35)/.27)**2)
        coords.append((110+i,474-level))
    for i in range(10):
        d.line((110+i*100,165,110+i*100,474),fill=GRID,width=1)
        text(d,(110+i*100,490),str(i),18,MUTED,'mt')
    d.line((110,161,110,474,1010,474),fill=MUTED,width=2)
    d.line(coords,fill=BLUE,width=4)
    for x,y,label in [(325,370,'2.14 min'),(672,223,'5.62 min'),(844,398,'7.35 min')]:
        text(d,(x,y),label,23,INK,'mm')
    return save(image,path,['표준액 크로마토그램','머무름 시간(min)','응답(mAU)','2.14 min','5.62 min','7.35 min'])


def flow(path):
    items=['세포배양','수확','정제 1·2','바이러스 불활화','여과','충전']
    image,d=graphic('FBX-101 공정 흐름도','제1공장 · 문서 분류용 개요')
    for index,label in enumerate(items):
        x=77+(index%3)*349
        y=174+(index//3)*235
        if index>=3:
            x=77+(5-index)*349
        d.rounded_rectangle((x,y,x+240,y+78),13,fill='#E9F5F6',outline=BLUE,width=3)
        text(d,(x+120,y+39),label,29,INK,'mm')
        if index in [0,1]:
            arrow(d,(x+250,y+39),(x+330,y+39))
        if index==2:
            arrow(d,(x+120,y+85),(x+120,y+220))
        if index in [3,4]:
            arrow(d,(x-12,y+39),(x-91,y+39))
    return save(image,path,items)


def stamp(path):
    image=Image.new('RGBA',(390,238),(255,255,255,0))
    d=ImageDraw.Draw(image)
    d.ellipse((86,9,302,225),outline='#9C3441',width=7)
    d.ellipse((96,19,292,215),outline='#9C3441',width=2)
    text(d,(194,91),'QA 확인',34,'#9C3441','mm')
    text(d,(194,138),'승인',51,'#9C3441','mm')
    return save(image,path,['QA 확인','승인'])


def signature(path):
    image=Image.new('RGBA',(410,134),(255,255,255,0))
    d=ImageDraw.Draw(image)
    d.line([(19,97),(52,47),(73,87),(102,28),(133,49),(98,99),(136,77),(162,39),
            (176,82),(211,44),(201,99),(290,50),(315,62),(368,49)], fill='#284262', width=5)
    d.arc((104,55,333,113),8,154,fill='#284262',width=3)
    return save(image,path)


def noisy(image, *, seed=1, angle=.8, coffee=False, gray=True, bleed=True):
    source=image.convert('L' if gray else 'RGB')
    background=246 if gray else (249,247,240)
    source=source.rotate(angle,resample=Image.Resampling.BICUBIC,fillcolor=background)
    values=np.asarray(source,dtype=np.int16)
    rng=np.random.default_rng(seed)
    height,width=values.shape[:2]
    lighting=np.linspace(3,-6,width)[None,:]+np.linspace(-2,4,height)[:,None]
    noise=rng.normal(0,2.0,(height,width))+lighting
    specks=rng.random((height,width))
    noise[specks<.0015]-=47
    noise[specks>.9985]+=37
    if bleed:
        ghost=np.asarray(source.transpose(Image.Transpose.FLIP_LEFT_RIGHT).convert('L').filter(ImageFilter.GaussianBlur(2.8)))
        noise -= (255-ghost)*.025
    out=Image.fromarray(np.clip(values+(noise if gray else noise[:,:,None]),0,255).astype('uint8')).convert('RGB')
    if coffee:
        d=ImageDraw.Draw(out,'RGBA')
        x,y=int(width*.81),int(height*.77)
        for i in range(5):
            d.arc((x+i,y+i,x+int(width*.12)-i,y+int(width*.12)-i),23+i*6,354-i*5,
                  fill=(118,70,32,38-i*5),width=5)
    return out


def form(title, subtitle, headers, rows, *, comment='', tick=True):
    image,d=graphic(title,subtitle,(1654,2339))
    x0,x1=120,1534
    text(d,(120,143),'Fabrikam Bio  |  제1공장',30,BLUE)
    d.rectangle((x0,225,x1,289),fill='#E4EDEF',outline=BLUE,width=2)
    step=(x1-x0)/len(headers)
    for idx,value in enumerate(headers):
        text(d,(x0+18+step*idx,257),value,27,BLUE,'lm')
    for index,row in enumerate(rows,1):
        y=289+(index-1)*70
        d.rectangle((x0,y,x1,y+70),fill='#F2F6F6' if index%2==0 else '#FFFFFF',outline=GRID,width=2)
        for idx,value in enumerate(row):
            x=x0+18+step*idx
            text(d,(x,y+35),value,29,INK,'lm')
        if tick and index%2:
            d.line((x1-98,y+38,x1-85,y+53,x1-60,y+23),fill='#36516B',width=4)
    if comment:
        text(d,(x0,342+len(rows)*70),comment,29,'#2E496D')
    return image


def paper_photo(page, target):
    thumb=page.resize((1120,1584),Image.Resampling.LANCZOS)
    thumb=noisy(thumb,seed=19,angle=2.2,coffee=True,gray=False)
    # Pillow inverse perspective coefficients in the source page coordinate system.
    skew=thumb.transform((1210,1690),Image.Transform.PERSPECTIVE,
                         (1.10,.031,-126,-.048,1.05,-40,.000035,-.000054),
                         Image.Resampling.BICUBIC,fillcolor='#33454A')
    px=np.asarray(skew,dtype=np.float32)
    shade=np.linspace(.71,1.025,1210)[None,:,None]*np.linspace(.99,.94,1690)[:,None,None]
    photo=Image.fromarray(np.clip(px*shade,0,255).astype('uint8')).filter(ImageFilter.GaussianBlur(.42))
    return save(photo,target,['EQ-COOL-02','압력 2.6 bar','현장 운전일지','설비팀 박O수','제1공장'])


def nameplate(path):
    image,d=graphic('설비 명판','Fabrikam Bio · 설비 식별용 모사 이미지')
    rng=np.random.default_rng(4)
    metallic=np.tile(np.linspace(170,226,840,dtype=np.float32),(347,1))
    metallic+=rng.normal(0,2.4,(347,1))
    plate=Image.fromarray(np.clip(metallic,0,255).astype('uint8')).convert('RGB')
    image.paste(plate,(130,155))
    d.rounded_rectangle((130,155,970,502),16,outline='#5F6C72',width=5)
    for x in [151,949]:
        for y in [177,480]:
            d.ellipse((x-7,y-7,x+7,y+7),fill='#58646A')
    entries=[('관리번호','EQ-UF-03'),('모델','UF-700 (가상)'),('일련번호','SN-2023-0417'),
             ('정격 온도','-86 °C'),('전원','220 V 60 Hz'),('제조사','가상냉동(주)')]
    for index,(k,v) in enumerate(entries):
        text(d,(225,190+47*index),k,29)
        text(d,(482,190+47*index),v,29)
    return save(image,path,[v for _,v in entries])


def build_visuals(photo_grid):
    media=WORK/'media'
    media.mkdir(exist_ok=True)
    board=Image.open(photo_grid).convert('RGB')
    width,height=board.size
    assets={}
    for idx,key in enumerate(['skid','pump','corrosion','cabinet','racks','tank','pipe','freezer','bench']):
        i,j=idx%3,idx//3
        crop=board.crop((round(i*width/3)+5,round(j*height/3)+5,round((i+1)*width/3)-5,round((j+1)*height/3)-5))
        assets[key]=save(crop,media/f'{key}.jpg')
    for idx,key,filename,title in [
        (1,'skid','냉각수설비_전경.jpg','냉각수 설비 전경'),(2,'pump','펌프P2_근접.jpg','펌프 P2 근접'),
        (3,'corrosion','배관_부식부위.jpg','배관 부식 부위'),(7,'racks','시료보관_냉동고_내부.jpg','시료 보관 냉동고 내부')]:
        target=register(f'IMG-{idx}',9,filename,title,department='설비',priority='P1' if idx==7 else 'P0',
                        purposes='structure chunking',notes='무문자 합성 사진.')
        target.write_bytes(assets[key].read_bytes())
    assets['vibration']=chart(register('IMG-4',9,'진동추이_2026Q3.png','2026년 냉각수 펌프 진동 추이',
                                       department='설비',purposes='ocr embedding_eval chunking'),
                              '냉각수 펌프 진동 추이', ['2026-07','2026-08','2026-09','2026-10'],
                              [('P-1',[2.1,2.2,2.4,2.5]),('P-2',[3.2,3.5,4.1,4.8])],
                              threshold=(4.5,'4.5 mm/s'))
    assets['pid']=pid(register('IMG-5',9,'냉각수계통_PID.png','냉각수 순환계통',
                               department='설비',purposes='ocr embedding_eval structure'))
    assets['flow']=flow(register('IMG-6',9,'공정흐름도_FBX101.png','FBX-101 공정 흐름도',priority='P1',
                                 department='생산',purposes='ocr embedding_eval'))
    assets['swab']=swab(media/'swab.png')
    assets['fishbone']=fishbone(media/'fishbone.png')
    assets['chromatogram']=chromatogram(media/'chromatogram.png')
    assets['stamp']=stamp(media/'stamp.png')
    assets['signature']=signature(media/'signature.png')
    return assets
