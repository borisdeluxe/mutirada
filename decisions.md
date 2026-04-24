# Decisions

Bewusst getroffene Entscheidungen. **DO NOT REVERT** ohne explizite Freigabe von Boris.

---

## Infrastruktur

### Agency-Server: Hetzner CAX31 (ARM Cloud)
- **Datum:** 2026-04-24
- **Specs:** 8 vCPU Ampere, 16 GB RAM, 160 GB NVMe, €16/Monat
- **Warum:** Bestes Preis-Leistungs-Verhaeltnis fuer den Agency-Stack ohne lokale LLMs. Dedizierte ARM-Cores, kein Noisy-Neighbor. 16 GB RAM reicht fuer Orchestrator + Postgres + Slack-Bot + mehrere Git-Worktrees parallel.
- **Konsequenz:** Alle LLM-Aufgaben laufen ueber die Anthropic API (Haiku fuer Gates/Reports, Sonnet/Opus fuer Implementierung/Security/QA). Keine lokale Inference.
- **Upgrade-Pfad:** Bei Bedarf fuer lokale Modelle spaeter auf Hetzner AX42 (64 GB DDR5, Ryzen 7, ~€49/Monat) wechseln.

### Keine lokalen LLMs in Phase 1
- **Datum:** 2026-04-24
- **Warum:** MiniMax M2 benoetigt 4x H100 GPUs — unrealistisch im Budget. CPU-Inference auf dem CAX31 waere zu langsam und frisst RAM das der Agency-Stack braucht. Haiku kostet ~€2/Monat fuer Gate-Checks bei realistischem Volumen — der Infrastruktur-Overhead fuer lokale Modelle lohnt sich dafuer nicht.
- **Konsequenz:** Model-Tiering ueber Anthropic API: Haiku fuer einfache Tasks (Gates, Format-Checks, Daily Reports), Sonnet fuer komplexe Tasks (Implementation, Security, Architecture), Opus nur bei explizitem Bedarf.
- **Reevaluation:** In Phase 3, wenn Volumen >100 Features/Monat oder grundsaetzlicher Wunsch nach lokaler Inference.
