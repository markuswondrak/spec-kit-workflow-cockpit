# Umsetzungs- und Migrationsplan: Spec-Kit Extended Flow

Dieser Plan beschreibt die vollständige Umstellung des Spec-Kit-Ökosystems:
1. `../spec-kit-extended-flow` sauber, verschlankt und katalogfähig hinstellen.
2. Den `extended-flow` als offiziellen Dogfooding-Workflow in `spec-kit-workflow-cockpit` einbinden und alle bisherigen Eigenbauten (`lean-workflow`, `arc42`, `lean-flow`, altes Bundle) restlos ablösen.

---

## 1. Geklärte Kernentscheidungen & Leitplanken

1. **Standard Spec-Kit Flow (Full SDD) statt Lean:**
   * Der `lean-flow` wird ausgemustert.
   * Extended Flow setzt auf den vollständigen Spec-Kit SDD-Lifecycle: `speckit.specify` → `speckit.plan` → `speckit.tasks` → `speckit.analyze` → `speckit.implement` → `speckit.converge` (Konvergenzschleife) → `documentation` → `finish`.
   * Für kleine, triviale Änderungen steht der schlanke `quick-flow` bereit.
2. **Gezielter Cleanup nach dem allerletzten Schritt:**
   * Das `specs/<feature-dir>`-Verzeichnis und der Pointer `.specify/feature.json` werden im letzten Schritt (`finish`) aufgeräumt, nachdem die Dokumentation final abgeglichen wurde.
   * **Strikte Invariante:** Das Run-Verzeichnis `.specify/workflows/runs/<run_id>/` darf **niemals** gelöscht werden (Eigentum der Engine; Löschen führt zu unhandled `FileNotFoundError` beim Speichern von `state.json`).
3. **`bug`-Extension im Bundle gebündelt:**
   * Die Core-Extension `bug` (v1.0.0) wird direkt in `bundle.yml` als Dependency deklariert. Dadurch installiert `specify bundle install` die Bug-Commands (`speckit.bug.assess`, `speckit.bug.fix`, `speckit.bug.test`) automatisch mit.
4. **Integration: opencode v1:**
   * Der Workflow zielt auf `opencode` v1.
   * Die built-in `git`-Extension von Spec-Kit muss deaktiviert sein (`specify extension disable git`), um Hänger bei `before_specify`-Hooks zu vermeiden.
5. **Installationsreihenfolge:**
   * Die lokale Dev-Installation wird zuerst zur Validierung verwendet.
   * Danach nutzt Cockpit standardmäßig den veröffentlichten GitHub-Catalog; Local Dev bleibt optional.

---

## 2. Phasenweiser Umsetzungsplan nach Repository

```
┌────────────────────────────────────────────────────────┐
│ Phase 1: Repo "../spec-kit-extended-flow" stabilisieren│
│  - Bug-Extension ins Bundle                            │
│  - Finish-Agent bereinigen (nur specs/ aufräumen)      │
│  - Unattended-Runtime Preamble absichern               │
│  - Catalog-System & build-catalog.sh aufbauen          │
│  - CI Workflow (.github/workflows/test.yml)            │
│  - Release 0.13.0 committen & taggen                   │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: Repo "spec-kit-workflow-cockpit" umstellen    │
│  - lokal validierten Extended Flow installieren         │
│  - Eigenbauten erst danach löschen                      │
│  - Setup, Tests und Doku auf Extended Flow umstellen    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: GitHub-/Release-Modus                          │
│  - veröffentlichte v0.13.0 installieren                 │
│  - GitHub-Catalog registrieren                          │
│  - Smoke-Test und Review-PR erstellen                    │
└────────────────────────────────────────────────────────┘
```

---

### Phase 1: Anpassungen in `../spec-kit-extended-flow`

#### 1.1 `bundle.yml` um `bug`-Extension erweitern
* In `bundle.yml` unter `provides.extensions` den Eintrag `id: "bug"`, `version: "1.0.0"` aufnehmen.
* Test `tests/test-bundle-manifest.sh` erweitern/verifizieren.

#### 1.2 `commands/speckit.extendedflow.finish.md` korrigieren (Sicherer Cleanup)
* **Lösch-Instruktion anpassen (Schritt 3):**
  * `runs/<run_id>/` **entfernen**: Der Agent darf niemals das Engine-Run-Verzeichnis löschen.
  * `specs/<feature-dir>/` und `.specify/feature.json` **löschen**: Wird wie gewünscht nach der Dokumentationsreconciliation aufgeräumt.
* **Commit/PR-Bedingung absichern:**
  * Wenn kein GitHub Issue vorhanden ist, keinen Fehler werfen, falls `gh` fehlt; Commit nur erzeugen, wenn Änderungen gestaged sind.

#### 1.3 Unattended Runtime Context bereitstellen
* Eine `workflow-runtime.md` im Preset anlegen oder `speckit.extendedflow.project-init` so schärfen, dass für Core-Befehle die Vorgabe gilt: keine interaktiven Rückfragen, fundierte Defaults treffen, Blocker als Output melden.

#### 1.4 HTTPS-Catalog-Infrastruktur aufbauen ("wie im Cockpit")
* Ordner `catalog/` erstellen mit:
  * `extension-catalog.json` (zeigt auf `artifacts/extendedflow-0.13.0.zip`)
  * `preset-catalog.json` (zeigt auf `artifacts/spec-kit-extended-flow-0.13.0.zip`)
  * `workflow-catalog.json` (zeigt auf raw Workflows)
  * `bundle-catalog.json` (zeigt auf `artifacts/spec-kit-extended-flow-bundle-0.13.0.zip`)
  * `artifacts/` für generierte ZIPs.
* Skript `scripts/build-catalog.sh` erstellen, das die Komponenten deterministisch packt.
* Skript `scripts/release.sh` fixen: Auch `bundle.yml` synchron hochzählen.

#### 1.5 CI Workflow aufsetzen
* `.github/workflows/test.yml` anlegen:
  * Führt bei Push und PR auf `main` alle Bash-Tests (`tests/test-*.sh`) aus.
  * Verifiziert `scripts/package-preset.sh` und `scripts/build-catalog.sh`.

#### 1.6 Release v0.13.0 finalisieren
* Alle 256 Tests verifizieren.
* Stand sauber committen und Tag `v0.13.0` vergeben.

---

### Phase 2: Anpassungen in `spec-kit-workflow-cockpit`

#### 2.1 Eigenbauten entfernen
* Verzeichnisse löschen:
  * `presets/lean-workflow/`
  * `extensions/arc42/`
  * `workflows/lean-flow/`
  * `bundles/workflow-cockpit/`
  * `catalog/artifacts/lean-workflow-*.zip`, `catalog/artifacts/arc42-*.zip`, `catalog/artifacts/workflow-cockpit-*.zip`

#### 2.2 `scripts/setup-speckit.sh` aktualisieren
* GitHub ist die Standardquelle: `--source github`.
* Der Cockpit-eigene Catalog pinnt die Extended-Flow-Version `v0.13.0`.
* Local Dev bleibt explizit verfügbar: `--source local --path PATH`.
* GitHub-Modus registriert die vier Cockpit-Catalog-Dateien und installiert das veröffentlichte
  Bundle.
* Local-Modus installiert Extension, Preset und die drei Workflows per `--dev`.

#### 2.3 Dokumentations-Verifikation absichern
* In Cockpits Root-`AGENTS.md` (wird vom `extendedflow.documentation`-Agenten zwingend als Tier-1-Kontext gelesen) den Prüfbefehl verankern:
  > *"When updating architecture documents under docs/, verify structural and line limits with: `python -m pytest tests/docs -q`."*

#### 2.4 Cockpit-Dokumentation & Living Architecture nachführen
* `CONTRIBUTING.md` & `README.md`: Dogfooding-Anleitung auf `spec-kit-extended-flow` aktualisieren.
* `docs/architecture/02-constraints.md`: Verweise auf `lean-workflow` durch `spec-kit-extended-flow` ersetzen.
* `docs/architecture/06-runtime-view.md`: Dogfooding-Workflow-Diagramm/Beschreibung auf Extended Flow umstellen.
* `docs/architecture/07-deployment-view.md`: Repräsentation der Werkzeuge anpassen.

#### 2.5 Tests aktualisieren
* `tests/docs/test_release_assets.py`:
  * Zeilenprüfungen auf `lean-workflow`, `arc42` und `lean-flow` anpassen auf die neuen `specify bundle install`- bzw. Catalog-Befehle.

---

### Phase 3: GitHub-/Release-Modus

* Erledigt: Extended Flow `v0.13.0` wurde veröffentlicht.
* Erledigt: GitHub-Catalog wurde im Cockpit registriert und das Bundle installiert.
* Erledigt: Smoke-Test bis zum Feature-Gate wurde ausgeführt.

---

### Phase 4: Verifikation nach der jeweiligen Installationsart

1. **Lokale Test-Suiten ausführen:**
   ```bash
   python -m pytest tests/unit tests/textual tests/contract tests/pty tests/docs -q
   ruff check workflow_cockpit tests
   ```
2. **Fresh-Bootstrap Test:**
    * In einer sauberen Umgebung `scripts/setup-speckit.sh --source local` sowie `--source github` testen.
3. **Cockpit UI Test-Run:**
   * Cockpit starten (`workflow-cockpit`).
    * Über die Launch-Maske `spec-kit-extended-flow` oder `spec-kit-quick-flow` starten.
   * Prüfen:
     * Workflow läuft non-interactive durch.
     * Gates stoppen sauber und lassen sich über Cockpit freigeben.
     * Nach Abschluss: `specs/` ist aufgeräumt, `state.json` existiert unversehrt, kein Crash der Engine, Cockpit zeigt erfolgreichen Status.

---

## 3. Risiken & Mitigation

| Risiko | Auswirkung | Mitigation |
|---|---|---|
| Engine-Crash bei Run-Abschluss | Workflow bricht am Ende mit Fehler ab | Strenges Verbot des Löschens von `runs/<run_id>` in `finish.md`. |
| Git-Extension Hook blockiert bei opencode | Agent wartet endlos auf `EXECUTE_COMMAND` | `specify extension disable git` im Setup-Skript fest verankert. |
| Zeilenlimit-Verletzung bei Doku-Updates | `tests/docs` schlägt fehl | Prüfregel für `pytest tests/docs` explizit in `AGENTS.md` verankert. |
| Offline-/Local-Entwicklung erschwert | Änderungen im Flow greifen nicht lokal | `--source local`-Flag in `setup-speckit.sh` für `--dev`-Verlinkung. |
