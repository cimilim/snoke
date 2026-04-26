# Snoke iOS (MVP)

Dieses Verzeichnis enthaelt ein SwiftUI-MVP fuer eine native Snoke-iOS-App,
die gegen das bestehende FastAPI-Backend spricht.

## Was ist enthalten?

- `SnokeIOS/App/` - App-Entry, Navigation, Session-Handling
- `SnokeIOS/Features/` - Onboarding, Dashboard, History (Chart), Settings
- `SnokeIOS/Networking/` - API-Client + Endpunktaufrufe
- `SnokeIOS/Notifications/` - lokale Daily Reminder (UNUserNotificationCenter)
- `SnokeIOS/Models/` - Codable-Modelle passend zum Backend
- `APP_STORE_CHECKLIST.md` - konkrete Schritte bis App Store Submission
- `APP_STORE_LISTING_DE.md` / `APP_STORE_LISTING_EN.md` - Store-Texte
- `RELEASE_NOTES_TEMPLATE.md` - Release Notes Vorlage

## In Xcode verwenden

Wichtig: Dieses Repo versioniert aktuell **nur den SwiftUI-Quellcode** unter `ios/SnokeIOS/`.
Ein `*.xcodeproj` wird **nicht** mit eingecheckt (siehe `.gitignore`), daher musst du dir lokal
ein Xcode-Projekt anlegen, das auf diese Quellen zeigt.

### Empfohlener, chaos-freier Aufbau (Single Source of Truth)

- **Code**: `ios/SnokeIOS/**` (bleibt die einzige Quelle)
- **Xcode-Projekt (lokal, nicht in Git)**: lege es z. B. unter `ios/SnokeIOSApp/` ab

### Schritt-fuer-Schritt (ohne Duplikate)

1. In Xcode ein neues Projekt erstellen:
   - iOS -> App
   - Product Name: `SnokeIOSApp` (oder `SnokeIOS`)
   - Interface: `SwiftUI`
   - Language: `Swift`
2. Projektordner unter `snoke/ios/` speichern (z. B. `snoke/ios/SnokeIOSApp/`).
3. Im Project Navigator: Rechtsklick auf deine App-Gruppe -> **Add Files to "<DeinAppName>"...**
4. Waehle den Ordner `snoke/ios/SnokeIOS/` aus.
   - **Copy items if needed**: AUS (sonst entstehen Duplikate)
   - **Target Membership**: AN (sonst wird es nicht gebaut)
5. Stelle sicher, dass es genau **einen** `@main ... : App` Entry-Point gibt (z. B. `SnokeApp`).
6. In der App unter Settings die Backend-URL setzen (HTTPS, z. B. `https://api.deine-domain.tld`).
7. Build & Run auf Simulator oder iPhone.

### Wenn Xcode "File not found" anzeigt

Das sind meist alte Tabs/Verweise nach Umbenennungen. Tab schließen und Datei neu aus dem
Project Navigator oeffnen; notfalls Projekt einmal schließen/neu oeffnen.

## Backend-Voraussetzung

- `POST /users/register`
- `GET /me/summary`
- `GET /me/probability`
- `GET /me/recommendation`
- `POST /events/batch`

## Naechste Schritte Richtung App Store

- App-Icon und Launch-Screen finalisieren
- Fehler- und Offline-Handling erweitern
- Privacy-Angaben fuer App Store Connect vorbereiten
- TestFlight-Build hochladen
- App-Store-Screenshots aus Dashboard/History/Settings erstellen
