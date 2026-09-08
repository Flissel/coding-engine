---
name: space-tool-implementation
description: Implement one tool of a VibeMind space in its generated FastMCP server, honouring the space contract's read/write, provenance and truth obligations. Use when filling a NotImplementedError stub in spaces/<id>/server.py.
---

# Space-Tool implementieren

Du füllst **genau ein** Tool im erzeugten MCP-Server eines VibeMind-Space.
Der Space-Vertrag ist die Vorgabe, nicht dein Entwurf.

## Wo du schreibst

`spaces/<space-id>/server.py` — sonst nirgends. Das ist **nicht** ein
`src/modules/…`-Projekt: keine NestJS-Struktur, kein Prisma, kein React. Die
Datei ist ein FastMCP-Server, der bereits vollständig verdrahtet ist.

Ersetze nur den Körper der einen Funktion, die dir genannt wurde. Signatur,
Dekorator und Name bleiben, wie sie sind — die Registry, das Agenten-Manifest
und die Tests hängen daran.

## Was der Vertrag dir vorgibt

Der Vertrag steht im Kontext. Daraus gilt:

- **`params`** sind die Parameter der Funktion. Erfinde keine dazu, lass keine weg.
- **`returns`** ist die Form der Rückgabe. Ein Tool mit `returns: {id: string}`
  gibt ein Dict mit `id` zurück, nicht einen nackten String.
- **`side_effect: read`** — nur lesen. Kein Schreibweg, auch kein „legt an,
  falls nicht vorhanden".
- **`side_effect: write`** — siehe unten, das ist der strengere Fall.

## Schreibende Tools

Ein schreibendes Tool trägt zwei Pflichten, und beide sind Teil der
Implementierung, nicht Beiwerk:

1. **Provenance.** Das zugehörige Event verlangt Nachweise (etwa
   `approval_ref`, `cost_ref`). Der Schreibweg muss sie mitführen und
   ablehnen, wenn sie fehlen — nicht stillschweigend ohne sie schreiben.
2. **Truth.** Der Vertrag deklariert eine Postcondition, die **unabhängig**
   nachgelesen wird. Deine Aufgabe ist es, so zu schreiben, dass diese
   Rückfrage den geschriebenen Zustand auch findet: gibt der Vertrag
   `match: id=eq.{result_id}` vor, muss die Rückgabe genau dieses `id`
   enthalten. Die Rückfrage selbst baust du nicht ein — sie läuft anderswo.

## Verboten

- **Kein stiller Erfolg.** Ein Körper, der ein leeres Ergebnis zurückgibt,
  statt zu tun, was das Tool verspricht, ist schlimmer als der Stub: die
  ganze Kette meldet dann Erfolg und nichts ist passiert. Wenn du etwas
  nicht implementieren kannst, lass `NotImplementedError` stehen — das Gate
  ist dafür da, das sichtbar zu machen.
- **Keine erfundenen Abhängigkeiten.** Was du importierst, muss zur Laufzeit
  des Space vorhanden sein.
- **Keine Änderungen an anderen Tools** derselben Datei.

## Fertig ist es, wenn

- die Funktion kein `NotImplementedError` mehr wirft,
- die Datei importierbar bleibt (`verify contract` lädt sie wirklich),
- die Rückgabe zu `returns` passt,
- und bei `write` die Provenance geprüft und das Truth-Feld gefüllt ist.
