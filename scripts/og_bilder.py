#!/usr/bin/env python3
"""Delingsbildene per tekstside (23.10.2026): ett bilde (1200 x 630) for hver
lagside og spørsmålsside, i samme stil som <liga>/og.png (scripts/make_og.py:
skriftene, ikonet og fargene derfra).

Innholdet kommer fra scripts/lag_sider.py (bilde_lag, bilde_sporsmal), laget
av de samme tallene som teksten på siden, i samme kjøring. lag_sider.py lagrer
det i PNG-filen (iTXt «tabellkalkulator»), sammenligner før den lagrer, og
skriver filen bare på nytt når innholdet er endret: da kommer bare endrede
bilder med i grunnlag-commiten, og en ny Pillow-versjon gir ikke nye filer av
seg selv. Palettbilde (64 farger,
uten dithering), så hvert bilde holder seg godt under 25 KB.
"""
from PIL import Image, ImageDraw, PngImagePlugin

import make_og as og

GUL = (224, 173, 74)       # #e0ad4a, kvalik på siden
ROD = (255, 107, 116)      # #ff6b74, nedrykk på siden
FARGER = 64


def _farge(liga, sone):
    if sone == "nedrykk":
        return ROD
    if sone == "kvalik":
        return GUL
    if sone == "gull" and liga == "obos":
        return og.BLUE           # direkte opprykk, som øverste sone i OBOS
    if sone == "plass":
        return og.INK
    return og.GREEN


def _passe(d, tekst, navn, stor, maks_b, minst=40):
    """Største skrift (ned til minst) der teksten får plass på én linje."""
    s = stor
    while s > minst and d.textlength(tekst, font=og.font(navn, s)) > maks_b:
        s -= 2
    return og.font(navn, s)


def _bryt(d, tekst, fnt, maks_b):
    """Linjer som får plass i bredden. Hardt mellomrom foran % og «poeng», så
    «90» og «%» ikke havner på hver sin linje (str.split() deler også ved
    hardt mellomrom, derfor split(" "))."""
    tekst = tekst.replace(" %", "\u00a0%").replace(" poeng", "\u00a0poeng")
    linjer, naa = [], ""
    for ord_ in tekst.split(" "):
        prov = f"{naa} {ord_}".strip()
        if naa and d.textlength(prov, font=fnt) > maks_b:
            linjer.append(naa)
            naa = ord_
        else:
            naa = prov
    return linjer + ([naa] if naa else [])


def _bunn(im, d):
    ikon = og.icon(52)
    im.paste(ikon, (56, 528), ikon)
    d.text((56 + 66, 534), "Tabellkalkulator", font=og.font("BarlowCondensed-Bold", 38), fill=og.INK)
    d.text((og.W - 56, og.H - 44), "tabellkalkulator.no", font=og.font("Barlow-SemiBold", 28), fill=og.MUTED, anchor="rs")


def tegn_lag(b):
    """Lagsiden: ligaen, lagnavnet, plass og poeng, og til høyre tallet fra
    tittelen («1 %» og «sjanse for topp 4»; to soner under hverandre)."""
    im = Image.new("RGB", (og.W, og.H), og.BG)
    d = ImageDraw.Draw(im)
    x0 = 56
    d.text((x0, 56), b["liga"], font=og.font("Barlow-SemiBold", 34), fill=og.MUTED)
    d.text((x0, 104), b["navn"], font=_passe(d, b["navn"], "BarlowCondensed-ExtraBold", 120, 540), fill=og.INK)
    # Plass og poeng som to tall med forklaring under, som en tabellrad.
    y = 278
    stor, liten = og.font("BarlowCondensed-ExtraBold", 96), og.font("Barlow-Medium", 30)
    x = x0
    for tall, ord_ in b["tall_venstre"]:
        d.text((x, y), tall, font=stor, fill=og.INK)
        d.text((x + 2, y + 112), ord_, font=liten, fill=og.MUTED)
        x += max(d.textlength(tall, font=stor), d.textlength(ord_, font=liten)) + 56
    if b.get("under"):
        d.text((x0, y + 160), b["under"], font=og.font("Barlow-Medium", 28), fill=og.MUTED)
    # Høyre: sjansen fra tittelen.
    px0, py0, px1, py1 = 640, 44, 1152, 586 - 56
    d.rounded_rectangle((px0, py0, px1, py1), radius=22, fill=og.PANEL, outline=og.LINE, width=2)
    # Blokkene (tall og tekst) måles etter blekket og står midt i panelet.
    tall, midt, en = b["tall"], (px0 + px1) // 2, len(b["tall"]) == 1
    stor = og.font("BarlowCondensed-ExtraBold", 170 if en else 112)
    tekst = og.font("Barlow-SemiBold", 38 if en else 32)
    lh, luft, mellom = (48 if en else 40), (30 if en else 22), 44
    blokker = []
    for z in tall:
        bb = d.textbbox((midt, 0), z["tall"], font=stor, anchor="mt")
        linjer = _bryt(d, z["tekst"], tekst, px1 - px0 - 60)
        blokker.append((z, bb, linjer, (bb[3] - bb[1]) + luft + len(linjer) * lh))
    y = py0 + ((py1 - py0) - sum(h for *_, h in blokker) - mellom * (len(blokker) - 1)) / 2
    for z, bb, linjer, h in blokker:
        d.text((midt, y - bb[1]), z["tall"], font=stor, fill=_farge(b["liga_id"], z["sone"]), anchor="mt")
        for j, linje in enumerate(linjer):
            d.text((midt, y + (bb[3] - bb[1]) + luft + j * lh), linje, font=tekst, fill=og.INK, anchor="mt")
        y += h + mellom
    _bunn(im, d)
    return im


def tegn_sporsmal(b):
    """Spørsmålssiden: ligaen, spørsmålet og svaret slik siden svarer."""
    im = Image.new("RGB", (og.W, og.H), og.BG)
    d = ImageDraw.Draw(im)
    x0, maks = 56, og.W - 2 * 56
    d.text((x0, 50), b["liga"], font=og.font("Barlow-SemiBold", 34), fill=og.MUTED)
    tittel = _passe(d, b["tittel"], "BarlowCondensed-ExtraBold", 84, maks, 56)
    d.text((x0, 96), b["tittel"], font=tittel, fill=og.INK)
    # Svaret i et panel, så stort som det får plass.
    px0, py0, px1, py1 = x0, 214, og.W - 56, 500
    d.rounded_rectangle((px0, py0, px1, py1), radius=22, fill=og.PANEL, outline=og.LINE, width=2)
    for s in range(50, 28, -2):
        f = og.font("Barlow-SemiBold", s)
        linjer = _bryt(d, b["svar"], f, px1 - px0 - 64)
        lh = int(s * 1.32)
        if len(linjer) * lh <= py1 - py0 - 56:
            break
    y = py0 + (py1 - py0 - len(linjer) * lh) / 2
    for linje in linjer:
        d.text((px0 + 32, y), linje, font=f, fill=og.INK)
        y += lh
    d.rounded_rectangle((px0, py0 + 24, px0 + 6, py1 - 24), radius=3, fill=_farge(b["liga_id"], b["sone"]))
    _bunn(im, d)
    return im


def skriv(fil, innhold, nokkel, tekst):
    """Tegner og lagrer bildet, med innholdet (tekst) i iTXt-feltet nokkel."""
    im = tegn_lag(innhold) if innhold["art"] == "lag" else tegn_sporsmal(innhold)
    info = PngImagePlugin.PngInfo()
    info.add_itxt(nokkel, tekst)
    fil.parent.mkdir(parents=True, exist_ok=True)
    im.quantize(colors=FARGER, dither=Image.Dither.NONE).save(fil, optimize=True, pnginfo=info)
