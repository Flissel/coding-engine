---
name: space-intake
description: Turn a description of a wanted VibeMind space into a validated space.contract.yaml, sharpening vague terms first instead of guessing. Use when a space is described in prose and no contract exists yet.
---

# Space-Intake

Aus einer Beschreibung wird ein **Vertrag**, nicht ein Text. Der Vertrag ist
das Ziel dieser Stufe: alles Weitere leitet sich deterministisch aus ihm ab.
Was hier ungenau bleibt, wird später nicht besser — es wird generiert.

## Zuerst die Begriffe, dann die Felder

Bevor du ein einziges Feld füllst: lies `spaces/_contract/CONTEXT.md`. Es ist
das Glossar des Space-Vertrags, mit einer `_Vermeiden_`-Zeile je Begriff.

**Fordere unscharfe Sprache heraus, statt sie zu übernehmen.** Wer „Eintrag"
und „Notiz" mischt, meint vielleicht zweierlei — und du baust sonst zwei
Tools für dieselbe Sache oder eines für zwei. Frage nach, solange die Antwort
den Vertrag ändern würde:

- „Du sagst *Eintrag* — ist das dasselbe wie die *Notiz* von eben, oder etwas
  anderes?"
- „*Speichern* — wohin? Und woran erkennt man danach von außen, dass es
  passiert ist?"
- „Wer darf das auslösen? Braucht es eine Freigabe?"

**Stoße mit konkreten Fällen an die Grenzen.** Nicht „soll man löschen
können", sondern: „Jemand löscht eine Notiz, die gerade offen ist — was
passiert?" Die Antwort entscheidet über Tools und Events.

**Prüfe gegen das, was schon da ist.** Beansprucht ein anderer Space denselben
Prefix? Gibt es die id schon? Der Intake-Gate sagt es dir, aber frag lieber
vorher.

## Was du schreibst

Genau eine Datei: `space.contract.yaml`. Kein Fließtext, keine Erklärung
daneben.

- **`id`** — Kleinbuchstaben, Ziffern, Unterstriche, beginnt mit einem
  Buchstaben. **Keine Bindestriche**: sie machen Task-ids mehrdeutig und sind
  in Umgebungsvariablen unbrauchbar.
- **`prefixes`** — der Namensraum, der diesem Space gehört. Kein zweiter
  Space darf ihn beanspruchen, sonst gewinnt beim Routen still der später
  eingetragene.
- **`tools`** — je Operation eine: `name`, `params`, `returns`,
  `side_effect: read|write`.
- **`events`** — je benannter Absicht eine, mit `tool` und
  `required_params`. Jedes Event beginnt mit einem der Prefixe.
- **`ui`**, **`runtime`** — Einbettung und Laufzeit.

## Schreibende Tools kosten mehr

`side_effect: write` ist keine Eigenschaft, sondern eine Verpflichtung. Das
zugehörige Event braucht **beides**:

1. `required_provenance` — die Nachweise, ohne die nicht geschrieben werden
   darf, üblich `[approval_ref, cost_ref]`. Die Routing-Schicht weist das
   Event sonst ab.
2. `truth` — die **unabhängige** Rückfrage, die den geschriebenen Zustand
   nachliest. Nicht der Selbstbericht der Operation, sondern eine neue
   Abfrage an die Quelle.

Verfügbar sind `truth:supabase_row` (mit `table`, optional `match`,
`expect`), `truth:http_ok` (mit `url`) und `truth:file_exists` (mit `path`).
Andere Arten existieren im System, lassen sich aber aus einem Space-Vertrag
nicht beschreiben — erfinde keine.

Gibt das schreibende Tool eine `id` zurück, leitet der Vertrag den Filter
`id=eq.{result_id}` selbst ab. Sonst musst du `truth.match` angeben.

## Fertig ist es, wenn das Gate schweigt

```
python -m mcp_plugins.servers.grpc_host.space_cli intake \
    --contract space.contract.yaml [--target <vibemind-os>]
```

Exit 0 heißt vollständig. Exit 1 nennt jede Lücke mit Feld, Problem und dem,
was sie schließen würde — arbeite sie ab und prüfe erneut.

**Rate nicht, um das Gate ruhigzustellen.** Ein erfundener Tabellenname macht
den Vertrag gültig und den Space falsch. Wenn eine Pflichtangabe offen bleibt,
weil sie niemand beantwortet hat, dann ist der Intake **nicht fertig** — sag
das, statt etwas einzusetzen.
