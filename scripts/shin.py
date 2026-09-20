"""Shins metode for å fjerne bookmakermarginen (Shin 1992/1993).

Modellerer marginen som at bookmakeren beskytter seg mot en andel z
"innsidere" som vet utfallet sikkert, i stedet for enkel proporsjonal
normalisering. Gir en mindre justering for favoritter og en større for
underdogs (favoritt-longshot-skjevhet), som proporsjonal normalisering
ikke fanger opp.

Fastpunktiterasjon verifisert mot referanseimplementasjonen i
github.com/mberk/shin (src/lib.rs).
"""
import math


def shin_probabilities(odds, max_iter=100, tol=1e-12):
    """odds: liste med desimalodds (f.eks. [H,D,A]). Returnerer (p, z) der
    p er de marginfrie sannsynlighetene (summerer til 1) og z er andelen
    "innsidere" Shin-modellen estimerer."""
    inv = [1.0/o for o in odds]
    B = sum(inv)
    n = len(odds)
    z = 0.0
    for _ in range(max_iter):
        z0 = z
        s = sum(math.sqrt(max(0.0, z*z + 4*(1-z)*io*io/B)) for io in inv)
        z = (s - 2) / (n - 2)
        z = min(max(z, 0.0), 0.999999)
        if abs(z - z0) < tol:
            break
    p = [(math.sqrt(max(0.0, z*z + 4*(1-z)*io*io/B)) - z) / (2*(1-z)) for io in inv]
    s = sum(p)
    p = [x/s for x in p]  # normaliser bort ev. restfeil fra iterasjonen
    return p, z


if __name__ == "__main__":
    # Rask sjekk mot proporsjonal normalisering på et par eksempler
    for odds in [[1.56, 4.80, 4.50], [4.58, 3.73, 1.67], [1.20, 6.5, 12.0]]:
        inv = [1/o for o in odds]
        s = sum(inv)
        prop = [x/s for x in inv]
        shin_p, z = shin_probabilities(odds)
        print(f"odds={odds}")
        print(f"  proporsjonal: {[round(x,4) for x in prop]}")
        print(f"  shin (z={z:.4f}): {[round(x,4) for x in shin_p]}")
