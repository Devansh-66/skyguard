import os, sys, glob, win32com.client
src = os.path.abspath(sys.argv[1])
out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "render")
os.makedirs(out, exist_ok=True)
for f in glob.glob(os.path.join(out, "*.png")):
    os.remove(f)
app = win32com.client.Dispatch("PowerPoint.Application")
pres = app.Presentations.Open(src, WithWindow=False)
pres.SaveCopyAs(os.path.join(out, "deck.pdf"), 32)
for i, s in enumerate(pres.Slides, 1):
    s.Export(os.path.join(out, f"slide-{i}.png"), "PNG", 1600, 900)
pres.Close(); app.Quit()
print("rendered", len(glob.glob(os.path.join(out, "*.png"))), "slides ->", out)
