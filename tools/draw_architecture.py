from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Circle, Polygon, Rectangle, FancyArrowPatch

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets'
OUT.mkdir(parents=True,exist_ok=True)
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')
plt.rcParams['font.family']='Noto Sans CJK JP'
plt.rcParams['axes.unicode_minus']=False
fig,ax=plt.subplots(figsize=(16,9),dpi=180)
ax.set_xlim(0,16); ax.set_ylim(0,9); ax.axis('off')
fig.patch.set_facecolor('#f6f8fb'); ax.set_facecolor('#f6f8fb')

# title
ax.text(.7,8.35,'HPM-DT Studio：场景优先的系统级电磁任务仿真架构',fontsize=23,fontweight='bold',color='#172033')
ax.text(.72,7.92,'物理对象是场景事实源；任务通过角色与组件查询选择任意数量对象；分析区域只属于探针与任务。',fontsize=11.5,color='#617087')

# left scene illustration panel
panel=FancyBboxPatch((.65,1.05),4.25,6.35,boxstyle='round,pad=.02,rounding_size=.18',fc='#0d1726',ec='#24344b',lw=1.4)
ax.add_patch(panel)
ax.text(.95,6.98,'① 物理场景',fontsize=15,fontweight='bold',color='white')
ax.text(.95,6.58,'Scene Graph / Entity + Components',fontsize=9.5,color='#91a4bd')
# ground grid
for x in [1.05,1.65,2.25,2.85,3.45,4.05,4.65]:
    ax.plot([x,x-.6],[1.55,3.35],color='#263950',lw=.55)
for y in [1.55,1.95,2.35,2.75,3.15]:
    ax.plot([1.05,4.65],[y,y],color='#263950',lw=.55)
# buildings
for x,y,w,h in [(2.0,2.2,.75,1.65),(3.45,2.0,.8,1.3)]:
    ax.add_patch(Polygon([[x,y],[x+w,y+.22],[x+w,y+h],[x,y+h-.22]],closed=True,fc='#50627a',ec='#8190a3',lw=1))
    ax.add_patch(Polygon([[x+w,y+.22],[x+w+.25,y+.36],[x+w+.25,y+h+.12],[x+w,y+h]],closed=True,fc='#3d4d63',ec='#8190a3',lw=.8))
# arrays
for x in [1.25,4.15]:
    ax.add_patch(Rectangle((x,1.45),.55,.22,fc='#16c8e8',ec='#9cf2ff',lw=1))
    for ix in range(4):
        for iy in range(2):
            ax.add_patch(Circle((x+.07+ix*.13,1.49+iy*.09),.018,fc='#e6fbff',ec='none'))
# aircraft
colors=['#f59e0b','#fb7185','#facc15']
pts=[(1.55,4.95),(3.0,5.55),(4.25,4.72)]
for (x,y),c in zip(pts,colors):
    ax.add_patch(Polygon([[x,y+.17],[x+.14,y],[x,y-.09],[x-.14,y]],closed=True,fc=c,ec='white',lw=.8))
# trajectories
ax.plot([1.2,1.55,2.55],[4.4,4.95,5.25],ls='--',lw=1.2,color=colors[0],alpha=.8)
ax.plot([4.1,3.0,2.1],[6.0,5.55,4.7],ls='--',lw=1.2,color=colors[1],alpha=.8)
ax.plot([3.8,4.25,4.55],[4.2,4.72,5.8],ls='--',lw=1.2,color=colors[2],alpha=.8)
# probe plane
ax.add_patch(Polygon([[1.05,3.45],[4.35,3.45],[4.65,4.05],[1.35,4.05]],closed=True,fc='#0ea5e9',ec='#7dd3fc',alpha=.2,lw=1))
ax.text(.98,1.2,'阵列平台 · 运动对象 · 建筑物 · 接收设备 · 探针',fontsize=9.2,color='#b8c6d8')

# pipeline boxes
x0=5.35; y=5.55; w=2.0; h=1.32; gap=.24
boxes=[
('② 组件装配','阵列 / 发射 / 接收\n运动 / 边界 / 不确定度','#2563eb'),
('③ 任务定义','角色查询选择参与对象\n时间网格 + 求解配置','#7c3aed'),
('④ 求解管线','多阵列标量场\n动态帧 + 探针采样','#059669'),
('⑤ 结果工作区','三维回放 / 场切片\n对象曲线 / 工程保存','#ea580c'),
]
for i,(title,body,color) in enumerate(boxes):
    x=x0+i*(w+gap)
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.02,rounding_size=.13',fc='white',ec='#d5deea',lw=1.2))
    ax.add_patch(FancyBboxPatch((x+.14,y+h-.39),1.02,.25,boxstyle='round,pad=.02,rounding_size=.08',fc=color,ec='none'))
    ax.text(x+.65,y+h-.265,title,ha='center',va='center',fontsize=9.5,fontweight='bold',color='white')
    ax.text(x+.16,y+.54,body,fontsize=9.5,color='#3e4c61',va='center',linespacing=1.55)
    if i<len(boxes)-1:
        ax.add_patch(FancyArrowPatch((x+w+.03,y+h/2),(x+w+gap-.03,y+h/2),arrowstyle='-|>',mutation_scale=13,lw=1.4,color='#8da0b8'))
ax.add_patch(FancyArrowPatch((4.92,6.2),(5.28,6.2),arrowstyle='-|>',mutation_scale=15,lw=1.7,color='#4d76b8'))

# lower principles
ax.text(5.4,4.72,'新内核的三个约束',fontsize=14.5,fontweight='bold',color='#223047')
principles=[
('A','对象不是“目标1”','任何实体均以 UUID 标识；行为来自组件，不来自名称。'),
('B','任务不写死数量','role:trackable、component:receiver 可选择 0、1、3 或 20 个对象。'),
('C','结果视觉优先','默认展示三维场景、时间线和对象曲线；验证与论文工具退居二线。'),
]
for i,(key,title,body) in enumerate(principles):
    yy=3.85-i*.9
    ax.add_patch(Circle((5.72,yy+.18),.22,fc=['#dbeafe','#ede9fe','#dcfce7'][i],ec='none'))
    ax.text(5.72,yy+.18,key,ha='center',va='center',fontsize=10,fontweight='bold',color=['#1d4ed8','#6d28d9','#047857'][i])
    ax.text(6.08,yy+.27,title,fontsize=11.4,fontweight='bold',color='#27364c')
    ax.text(6.08,yy-.02,body,fontsize=9.5,color='#617087')

# boundaries card
ax.add_patch(FancyBboxPatch((11.7,1.18),3.55,3.33,boxstyle='round,pad=.02,rounding_size=.16',fc='#fff7ed',ec='#fed7aa',lw=1.2))
ax.text(12.02,4.08,'研究边界',fontsize=13.5,fontweight='bold',color='#9a3412')
bounds=['系统级、任务级、归一化模型','不替代 CST / HFSS / COMSOL','不输出真实毁伤距离或器件阈值','旧算法仅通过适配器接入新内核']
for i,t in enumerate(bounds):
    yy=3.55-i*.62
    ax.add_patch(Circle((12.03,yy),.055,fc='#f97316',ec='none'))
    ax.text(12.22,yy,t,va='center',fontsize=9.6,color='#713f12')

ax.text(.72,.48,'HPM-DT Studio 0.1 Alpha · Scene First Reboot',fontsize=8.8,color='#8795a8')
fig.savefig(OUT/'04_场景优先系统架构图.png',bbox_inches='tight',facecolor=fig.get_facecolor())
fig.savefig(OUT/'04_场景优先系统架构图.svg',bbox_inches='tight',facecolor=fig.get_facecolor())
