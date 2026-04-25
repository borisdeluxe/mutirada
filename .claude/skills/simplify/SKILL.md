---
name: simplify
description: Simplify code after implementation - remove complexity, improve readability
---

# Simplify Skill

Nach der Implementierung: Code vereinfachen ohne Funktionalität zu ändern.

## Wann anwenden

- Nach erfolgreicher Implementierung (Tests grün)
- Vor Code Review / QA
- Bei Code der "funktioniert aber hässlich ist"

## Checkliste

- [ ] Alle Tests laufen noch
- [ ] Keine neuen Features hinzugefügt
- [ ] Komplexität reduziert

## Simplify-Regeln

### 1. Entfernen

- Ungenutzter Code (dead code)
- Überflüssige Abstraktionen
- Doppelte Logik
- Auskommentierter Code
- Debug-Statements

### 2. Vereinfachen

- Lange Funktionen aufteilen (max 20-30 Zeilen)
- Tiefe Verschachtelung flacher machen
- Komplexe Conditionals extrahieren
- Magic Numbers durch Konstanten ersetzen

### 3. Benennen

- Variablen: was sie enthalten, nicht wie sie berechnet wurden
- Funktionen: was sie tun, nicht wie
- Keine Abkürzungen außer etablierte (id, url, etc.)

### 4. Nicht tun

- Keine neuen Features
- Keine Performance-Optimierung (außer offensichtlich)
- Keine Architektur-Änderungen
- Keine Dependency-Updates

## Hard Gate

Nach jedem Schritt: Tests laufen lassen. Bei Rot: Schritt rückgängig machen.
