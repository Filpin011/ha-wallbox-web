# Wallbox WEB per Home Assistant

[![Apri in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Filpin011&repository=ha-wallbox-web&category=integration)
[![Aggiungi integrazione](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wallbox_web)
[![Validate](https://github.com/Filpin011/ha-wallbox-web/actions/workflows/validate.yml/badge.svg)](https://github.com/Filpin011/ha-wallbox-web/actions/workflows/validate.yml)
[![Tests](https://github.com/Filpin011/ha-wallbox-web/actions/workflows/tests.yml/badge.svg)](https://github.com/Filpin011/ha-wallbox-web/actions/workflows/tests.yml)

> **Progetto indipendente e non ufficiale.** Nato dallo studio di come le colonnine comunicano sulla rete locale
> (interoperabilità). **Non è affiliato, approvato né supportato da SCAME PARRE S.p.A.** "Scame" e i marchi
> collegati appartengono ai rispettivi titolari e sono citati solo per indicare i dispositivi compatibili. Nessuna
> garanzia: lo usi a tuo rischio; gli interventi sull'impianto elettrico spettano a installatori qualificati.
> Dettagli: [DISCLAIMER.md](DISCLAIMER.md).

Integrazione personalizzata che porta in Home Assistant le colonnine di ricarica gestite da **Wallbox WEB**
(l'app web self-hosted per wallbox compatibili Scame su rete locale). Ogni colonnina diventa un **dispositivo** con
sensori, comandi e il contatore di energia per la **dashboard Energia**. Per la card con l'aspetto dell'app vedi
[wallbox-web-card](https://github.com/Filpin011/wallbox-web-card).

![Icona](custom_components/wallbox_web/brand/icon.png)

## Requisiti

- Home Assistant **2026.11** o successivo (HAOS, Container o Core).
- Un server **Wallbox WEB** con l'API v1, in uno dei due modi:
  - **self-hosted** (Docker, Coolify, …) raggiungibile da Home Assistant, es. `https://wallbox.example.com`;
  - **add-on** di Home Assistant (viene rilevato da solo).
- Per il server self-hosted: un **token API** creato nell'app (vedi sotto).

L'integrazione non parla mai direttamente con la colonnina: passa dal server, che condivide l'unica connessione
con la colonnina tra app, registratore delle ricariche e Home Assistant.

## Installazione

### Con HACS (consigliato)

1. Premi il pulsante **Apri in HACS** qui sopra, oppure in HACS › ⋮ › **Repository personalizzati** aggiungi
   `https://github.com/Filpin011/ha-wallbox-web` con tipo **Integrazione**.
2. Cerca **Wallbox WEB** › **Scarica**.
3. **Riavvia** Home Assistant (Impostazioni › Sistema › ⋮ › Riavvia).

### Manuale (Samba / File editor / Studio Code Server)

1. Scarica l'ultima [release](https://github.com/Filpin011/ha-wallbox-web/releases) e copia la cartella
   `custom_components/wallbox_web` in `/config/custom_components/wallbox_web` (con l'add-on Samba:
   `\\homeassistant\config\custom_components\`).
2. Riavvia Home Assistant.

## Configurazione

### Server self-hosted

1. In Wallbox WEB, come amministratore: **Menu › Token API › +**, nome `Home Assistant`, permessi
   **Lettura e comandi** (o *Solo lettura* se vuoi solo i sensori). Copia il token `wbx_…`: è mostrato una volta sola.
2. In Home Assistant: **Impostazioni › Dispositivi e servizi › Aggiungi integrazione › Wallbox WEB** (o il pulsante
   qui sopra).
3. Inserisci:
   - **URL**: indirizzo del server, es. `https://wallbox.example.com` (senza `/` finale);
   - **Token API**: il token `wbx_…`;
   - **Verifica certificato SSL**: lascia attivo; disattivalo solo per un certificato autofirmato in LAN.

### Add-on

Avvia l'add-on Wallbox WEB: Home Assistant mostra **"Nuovo dispositivo trovato: Wallbox WEB"** in Impostazioni ›
Dispositivi e servizi. Premi **Configura** › **Invia**. Non serve inserire nulla.

### Token revocato o URL cambiato

- Token non più valido → notifica **Riautenticazione necessaria**: incolla un nuovo token.
- Nuovo indirizzo del server → ⋮ dell'integrazione › **Riconfigura**.

## Cosa ottieni

Per ogni colonnina un dispositivo (produttore, modello, numero di serie, firmware, link alla pagina dell'app) con:

| Tipo | Entità |
|---|---|
| Sensori | Stato, Potenza, Energia ricarica, **Energia totale**, Durata ricarica, Corrente L1 (L2/L3 su trifase, disattivate), Tensione (disattivata), Potenza massima disponibile, Limite di potenza, Potenza esterna (disattivata), Errore, Programmazioni attive, Energia / Costo / Risparmio ultima ricarica, Tessera (disattivata) |
| Sensori binari | Connessa, In carica, Problema, Programmazione attiva, Raggiungibile |
| Pulsanti | Avvia ricarica, Pausa ricarica, Riprendi ricarica, Ferma ricarica (attivi solo quando l'azione è possibile) |
| Numero | Corrente massima (6 A … massimo della colonnina) |
| Selezione | Modalità di funzionamento (Libera / Personale) |

Le colonnine aggiunte dopo compaiono da sole. Aggiornamento dei dati: **push** (eventi dal server) con controllo di
riserva ogni 30 secondi.

### Dashboard Energia

Impostazioni › Dashboard › **Energia** › *Consumo elettrico individuale dei dispositivi* › **Aggiungi dispositivo** ›
scegli **`<colonnina> Energia totale`** (consumo istantaneo facoltativo: **`<colonnina> Potenza`**). Usa *Energia
totale* (cresce sempre), non *Energia ricarica* (si azzera a ogni sessione).

### Esempio di automazione

```yaml
alias: Avvisami a fine ricarica
triggers:
  - trigger: state
    entity_id: binary_sensor.garage_in_carica
    from: "on"
    to: "off"
actions:
  - action: notify.mobile_app_telefono
    data:
      message: >-
        Ricarica finita: {{ states('sensor.garage_energia_ultima_ricarica') }} kWh,
        {{ states('sensor.garage_costo_ultima_ricarica') }} €
```

## Limiti noti

- Una ricarica avviata con una tessera RFID potrebbe non essere fermabile da Home Assistant (la colonnina può
  rifiutare il comando).
- Se il server non espone ancora l'API v1, la configurazione risponde "Il server non espone l'API v1": aggiorna
  Wallbox WEB.

## Risoluzione problemi

- **Impossibile connettersi**: apri l'URL dal browser della stessa rete di Home Assistant; controlla certificato e
  porta.
- **Pulsanti non disponibili**: il token è di sola lettura, oppure l'azione non è possibile nello stato attuale.
- **Diagnostica**: Impostazioni › Dispositivi e servizi › Wallbox WEB › ⋮ › *Scarica diagnostica* (token, indirizzi
  e numeri di serie sono oscurati). Log: ⋮ › *Abilita registrazione di debug*.

## Rimozione

Impostazioni › Dispositivi e servizi › Wallbox WEB › ⋮ › **Elimina**; poi rimuovi l'integrazione da HACS (o la
cartella `custom_components/wallbox_web`) e revoca il token nell'app.

---

## English (short)

> **Independent, unofficial project**, based on a study of how the stations communicate on the local network
> (interoperability). **Not affiliated with, endorsed or supported by SCAME PARRE S.p.A.**; trademarks belong to
> their owners and are used only to identify compatible devices. No warranty, use at your own risk; electrical work
> must be done by qualified installers. See [DISCLAIMER.md](DISCLAIMER.md).

Custom integration for **Wallbox WEB** servers (self-hosted, or the Home Assistant add-on discovered automatically).
Each charging station becomes a device with sensors (status, power, session / lifetime energy for the Energy
dashboard, duration, currents, errors, last charge cost and saving), binary sensors, Start / Pause / Resume / Stop
buttons, a max-current number and a behaviour-mode select. Push updates (server-sent events) with a 30 s polling
fallback. Install through HACS (custom repository, category *Integration*) or copy `custom_components/wallbox_web`
to `/config/custom_components/`, restart, then add *Wallbox WEB* with the server URL and an API token
(app › Menu › API tokens). Requires Home Assistant 2026.11+.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Quick start: open in the dev container (or a Python 3.14 venv),
`scripts/setup`, `scripts/lint`, `scripts/test`, `scripts/develop` (Home Assistant on http://localhost:8123 with
this integration).

## License

[MIT](LICENSE)
