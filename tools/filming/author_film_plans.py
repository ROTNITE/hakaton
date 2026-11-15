"""Reproduce the presentation shot lists; all positions are Unreal centimeters."""
from pathlib import Path
import json


def rail(name,seconds,eye0,eye1,look0,look1=None,fov=48,until=None,follow=None):
    value={'id':name,'frames':round(seconds*30),'wait_frames':20,'keys':[
        {'u':0,'eye_cm':eye0,'look_cm':look0,'fov':fov},
        {'u':1,'eye_cm':eye1,'look_cm':look1 or look0,'fov':fov}]}
    if until is not None:value['wait_until_s']=until
    if follow:value['follow']=follow
    return value


def plans():
    environment=[
        rail('01-city',8,[-6500,-8000,16000],[-2500,-4500,12500],[6500,6500,0],[7000,7000,400],50),
        rail('02-damage',4,[4700,1400,1800],[5000,2600,2000],[4350,2180,800],[4350,2180,500],52),
        rail('03-collapse',7,[7550,5300,1000],[8200,5350,900],[7800,6500,450],fov=60,until=29),
        rail('04-fire',6,[12500,9600,1600],[12200,9800,1250],[10900,7950,300],fov=50,until=44.5),
        rail('05-water',5,[16500,10300,1100],[16200,11100,950],[14000,13000,40],fov=52,until=64),
        rail('06-fault',4,[8100,16400,900],[7100,16300,650],[7800,14500,-50],fov=58),
        rail('07-smoke',4,[10000,500,900],[10500,1000,700],[10000,2300,400],fov=55,until=101),
        rail('12-closing',6,[-2500,-4500,12500],[-6500,-8000,16000],[7000,7000,400],[6500,6500,0],50,until=110)
    ]
    core=[
        rail('07-recon',7,[-950,-650,450],[-650,800,450],[0,0,40],fov=48,until=8,follow='mobile-2'),
        rail('08-pickup',8,[-850,-650,420],[-800,450,350],[0,0,75],fov=48,until=31,follow='mobile-0'),
        rail('09-failure',5,[-800,500,400],[-1000,550,550],[0,0,80],fov=50,until=43,follow='mobile-0'),
        rail('10-recovery',10,[-950,-600,480],[-800,450,380],[0,0,75],fov=48,until=150,follow='mobile-1'),
        rail('11-inbound',6,[-1050,-650,450],[-950,600,400],[0,0,90],fov=48,until=166,follow='mobile-1'),
        rail('12-base-approach',8,[500,-1000,1900],[600,-700,1600],[2300,2200,130],fov=52,until=269),
        rail('13-handover',1,[600,-700,1600],[650,-600,1550],[2300,2200,130],fov=52)
    ]
    core[-1]['wait_for_delivered']=1
    return {
        'environment-plan.json':{'format':'metarescue.film.v1','fps':30,'warmup_frames':120,'shots':environment},
        'core-plan.json':{'format':'metarescue.film.v1','fps':30,'warmup_frames':120,'shots':core}
    }


def edit_spec(environment_take,core_take,smoke_take=None):
    environment_take=Path(environment_take).resolve();core_take=Path(core_take).resolve()
    verified=json.loads((core_take/'verification.json').read_text(encoding='utf-8'))
    if not verified.get('passed') or verified.get('mission',{}).get('episode_status')!='success':
        raise ValueError('This story requires its verified successful Core take')
    if not json.loads((environment_take/'verification.json').read_text(encoding='utf-8')).get('passed'):
        raise ValueError('Environment take must be verified first')
    smoke_take=Path(smoke_take).resolve() if smoke_take else environment_take
    if not json.loads((smoke_take/'verification.json').read_text(encoding='utf-8')).get('passed'):
        raise ValueError('Smoke reshoot must be verified first')
    environment_label='ПОСТАНОВОЧНАЯ СРЕДА · UNREAL ENGINE'
    core_label='РЕАЛЬНАЯ CORE-МИССИЯ · NSGA-II ×2 · AI MOCK'
    rows=[]
    def add(take,identity,kicker,title,subtitle='',seconds=4.5):
        rows.append({'id':identity,'frames':str(take/'capture'/identity),'kicker':kicker,'title':title,'subtitle':subtitle,
                     'provenance':core_label if take==core_take else environment_label,'title_seconds':seconds})
    add(environment_take,'01-city','METAEVOLUTION / RESCUE','Когда помощь должна успеть',
        'Разведка и эвакуация в городе после катастрофы',5.8)
    add(environment_take,'02-damage','01 / ГОРОД ПОСЛЕ КАТАСТРОФЫ','Повреждённые кварталы','',3.6)
    add(environment_take,'03-collapse','02 / СРЕДА МЕНЯЕТСЯ','Вторичные обвалы','Физическая сцена · постановочная лента событий',4.5)
    add(environment_take,'04-fire','03 / ОПАСНЫЕ УЧАСТКИ','Огонь и повреждённая инфраструктура','',4.5)
    add(environment_take,'05-water','04 / ЗАТОПЛЕНИЕ','Вода меняет доступность улиц','',4)
    add(environment_take,'06-fault','05 / ПОВРЕЖДЕНИЯ ДОРОГ','Город диктует маршрут','',3.6)
    add(smoke_take,'07-smoke','06 / ВИДИМОСТЬ','Дымовые зоны','',3.6)
    add(core_take,'07-recon','07 / СИСТЕМА В ДЕЙСТВИИ','Разведка с воздуха','Наблюдения передаются в систему управления',5.5)
    add(core_take,'08-pickup','08 / ЭВАКУАЦИЯ','Принять пострадавшего','Реальная погрузка в управляемой Core-миссии',4.5)
    add(core_take,'09-failure','09 / ОТКАЗ НОСИТЕЛЯ','Что происходит при отказе','Контролируемый сценарий: отказ привода с грузом',4)
    add(core_take,'10-recovery','10 / ПРОДОЛЖЕНИЕ МИССИИ','Другой робот принимает пострадавшего','Повторная погрузка после отказа носителя',5.5)
    add(core_take,'11-inbound','11 / ПЕРЕВОЗКА','Вернуть человека в безопасность','',4.5)
    add(core_take,'12-base-approach','','','',0)
    add(core_take,'13-handover','','','',0)
    rows[-1]['provenance']='CORE · ФАКТИЧЕСКАЯ ПЕРЕДАЧА · ПАУЗА ПОСЛЕ МИССИИ'
    add(environment_take,'12-closing','METAEVOLUTION / RESCUE','MetaEvolution Rescue',
        'Среда → наблюдения → план → действие',5.5)
    return {'fps':30,'shots':rows,'credit':'Нативные кадры Unreal. Камеры и showcase постановочные. Отдельная Core-миссия: NSGA-II ×2 / AI MOCK, без внешних AI-запросов. Музыка синтезирована специально для ролика.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--environment-take',type=Path);parser.add_argument('--core-take',type=Path)
    parser.add_argument('--smoke-take',type=Path)
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    if bool(args.environment_take)!=bool(args.core_take):parser.error('Both verified takes are required to author an edit')
    if args.smoke_take and not args.environment_take:parser.error('Smoke reshoot requires an edit with both main takes')
    for name,value in plans().items():
        path=args.directory/name
        with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
        print(path)
    if args.environment_take:
        path=args.directory/'edit.json'
        with path.open('x',encoding='utf-8') as stream:json.dump(edit_spec(args.environment_take,args.core_take,args.smoke_take),stream,ensure_ascii=False,indent=2)
        print(path)
