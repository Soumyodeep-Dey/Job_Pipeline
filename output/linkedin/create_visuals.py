from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
W = H = 1200
BG = '#0c1425'
CARD = '#17243b'
WHITE = '#f1f5fc'
MUTED = '#a9bad3'
CYAN = '#5ae0cf'
FONT = Path('C:/Windows/Fonts')

def font(size, bold=False):
    return ImageFont.truetype(str(FONT / ('segoeuib.ttf' if bold else 'segoeui.ttf')), size)

STEPS = [
    ('01', 'Configure', 'Excel companies + career links', 'Import company lists and workbook matching rules.'),
    ('02', 'Discover', 'Greenhouse / Lever / Ashby', 'Read supported job feeds through bounded requests.'),
    ('03', 'Evaluate', 'Suitability + duplicate checks', 'Check role, location and experience; store evidence.'),
    ('04', 'Assess', 'One-resume skill coverage', 'Compare explicit required skills with one resume.'),
    ('05', 'Review', 'Dashboard + readiness checklist', 'Review eligibility and prepare the application.'),
    ('06', 'Track', 'Manual submission + follow-ups', 'User submits externally, then records the outcome.'),
]
POSITIONS = [(70, 330), (430, 330), (790, 330), (70, 555), (430, 555), (790, 555)]

def text(d, xy, value, size, color=WHITE, bold=False):
    d.text(xy, value, fill=color, font=font(size, bold))

def render(active=None, phase=0):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((70, 65, 372, 108), radius=20, fill='#203c3d')
    text(d, (91, 72), 'LEARNING PROTOTYPE', 22, CYAN, True)
    text(d, (70, 132), 'JOB PIPELINE', 78, WHITE, True)
    text(d, (74, 230), 'From company lists to a clearer application workflow.', 30, MUTED)
    for i, ((n, title, sub, _), (x, y)) in enumerate(zip(STEPS, POSITIONS)):
        highlighted = active is None or active == i
        d.rounded_rectangle((x, y, x + 340, y + 195), radius=20,
                            fill=CARD, outline=CYAN if highlighted else '#30405b', width=3 if highlighted else 1)
        text(d, (x + 22, y + 17), n, 26, CYAN, True)
        text(d, (x + 22, y + 60), title, 35, WHITE, True)
        # Split descriptions to preserve generous margins.
        lines = {
            0: ['Excel companies', '+ career links'],
            1: ['Greenhouse / Lever', '/ Ashby'],
            2: ['Suitability', '+ duplicate checks'],
            3: ['One-resume', 'skill coverage'],
            4: ['Dashboard', '+ readiness checklist'],
            5: ['Manual submission', '+ follow-ups'],
        }[i]
        for j, line in enumerate(lines):
            text(d, (x + 22, y + 115 + j * 29), line, 24, MUTED)
    text(d, (70, 786), 'WORKFLOW EXPLAINER', 21, CYAN, True)
    if active is None:
        text(d, (70, 831), 'Discover. Understand. Review. Track.', 37, WHITE, True)
        text(d, (70, 892), 'Job suitability and resume coverage are separate decisions.', 27, MUTED)
    else:
        text(d, (70, 831), f'{active + 1}/6  {STEPS[active][1]}', 37, WHITE, True)
        text(d, (70, 892), STEPS[active][3], 27, MUTED)
    for i in range(6):
        x = 70 + i * 178
        d.rounded_rectangle((x, 960, x + 164, 967), radius=3,
                            fill=CYAN if active is None or i <= active else '#30405b')
    text(d, (70, 1010), 'Python  /  FastAPI  /  PostgreSQL  /  Docker', 28, WHITE, True)
    text(d, (70, 1071), 'Under active development. External applications are submitted manually.', 24, MUTED)
    text(d, (70, 1113), 'Architecture illustration - not a live dashboard recording.', 22, MUTED)
    return im

poster = render()
poster.save(OUT / 'Job_Pipeline_LinkedIn.png')
frames = [render(i) for i in range(6)] + [poster]
frames[0].save(OUT / 'Job_Pipeline_Workflow.gif', save_all=True,
               append_images=frames[1:], duration=[1600] * 6 + [2400],
               loop=0, optimize=True, disposal=2)
with Image.open(OUT / 'Job_Pipeline_Workflow.gif') as gif:
    print('GIF:', gif.size, 'frames:', gif.n_frames)
    for i in range(gif.n_frames):
        gif.seek(i)
        gif.load()
print('Poster:', OUT / 'Job_Pipeline_LinkedIn.png')
print('Animation:', OUT / 'Job_Pipeline_Workflow.gif')
