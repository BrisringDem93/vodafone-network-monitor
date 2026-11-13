# Vodafone Network Monitor

Prototipo locale indipendente per Windows 11, senza dipendenze Python esterne. Raccoglie campioni nella rete locale e li conserva in SQLite. **Non è ancora un prodotto completo o verificato su Windows 11 e sulla Vodafone Wi-Fi 6 Station.**

## Installazione e avvio

1. Installare Python 3.10 o successivo da python.org, includendo il Python Launcher per Windows.
2. Scaricare il progetto in una cartella permanente e fare doppio clic su `Avvia.vbs`. Si apre `http://127.0.0.1:8765/`; non è necessario aprire un terminale. Se la porta è occupata, chiudere l'altra istanza.
3. La raccolta si avvia automaticamente. Usare **Arresta monitoraggio** per sospenderla e **Esci dall'applicazione** per terminare anche il server. Chiudere soltanto la scheda del browser non termina il processo.
4. Per avviare con Windows, creare un **collegamento** a `Avvia.vbs` nella cartella Esecuzione automatica dell'utente (`Win+R`, `shell:startup`). Rimuovere il collegamento per disattivare l'avvio automatico; non copiare il file stesso.

Lo storico si trova in `%LOCALAPPDATA%\VodafoneNetworkMonitor\history.sqlite3`; è possibile effettuare un backup con l'applicazione arrestata. La dashboard ascolta esclusivamente su `127.0.0.1`; non esporre la porta a reti esterne. Non modifica router, DNS, rete o firewall.

## Funzioni e limiti

* Ogni circa due secondi, `netsh wlan show interfaces` fornisce i campi disponibili della prima scheda e `ping` interroga `192.168.1.1`, `1.1.1.1` e `8.8.8.8` in parallelo. I nomi dei campi di `netsh` sono riconosciuti in italiano e inglese; altre lingue o formati potrebbero non funzionare. Timeout, schede assenti e campi non disponibili sono registrati come valori mancanti. Il segnale percentuale **non** è un RSSI in dBm: il valore dBm rimane vuoto. La velocità di collegamento non è throughput Internet.
* Le statistiche di latenza, perdita e jitter usano i ping osservati nell'intervallo selezionato. Il jitter è la media delle differenze assolute tra risposte consecutive, senza interpolare timeout. Le anomalie rilevano gateway irraggiungibile, entrambi i target Internet irraggiungibili, latenza gateway e segnale debole; le ultime due soglie sono configurabili. Le interruzioni del monitoraggio terminano le anomalie aperte, non dimostrano che il problema sia cessato.
* La dashboard mostra lo storico, le anomalie e i log importati, con filtri temporali, dispositivo e categoria. La timeline dei log usa **l'ora di importazione**, non la data dichiarata dal router; i grafici usano scale indipendenti. Il filtro dispositivo si applica ai campioni, non ai log né alle anomalie.
* È possibile importare manualmente un JSON ottenuto con accesso autorizzato dalla Station; sono riconosciuti oggetti contenenti `logdetails` e almeno uno tra `date`, `time`, `category` ed `error`. Gli oggetti originali sono conservati nel database e deduplicati per contenuto identico, senza classificare automaticamente `error=1` come critico. Le occorrenze esattamente identiche non sono distinguibili. JSON differenti o strutture non riconosciute vengono rifiutati.
* **Non sono implementati** accesso automatico ogni 30 secondi all'endpoint Station, autenticazione/cookie/CSRF del router, importazione TAR, classificazione dei log, velocità effettiva download/upload o speed test programmati, raccolta del driver e RSSI in dBm. Non è stato possibile studiare una risposta reale o verificare firmware e autenticazione. Non disabilitare la verifica TLS né condividere credenziali per aggirare questi limiti.
* L'esportazione ZIP copre 15 minuti, 1 ora, 24 ore o un intervallo personalizzato. Contiene misurazioni CSV, eventi JSON, anomalie JSON, informazioni tecniche disponibili e README. Per prevenire fughe di dati, il testo libero e i campi sconosciuti degli eventi sono oscurati; rimangono solo date, ore, categorie e flag rigorosamente convalidati. Gli originali rimangono esclusivamente nel database locale. SSID, BSSID, testo `netsh` e altri identificatori sono esclusi. I log sono selezionati per data di importazione. Verificare sempre lo ZIP prima di condividerlo.
* Lo storico non ha una politica di eliminazione automatica; con intervalli lunghi la dashboard può richiedere più memoria. Conservare il database locale in una posizione protetta: i log originali potrebbero contenere dati personali o credenziali.

## Verifica per sviluppatori

Eseguire `python -m unittest -v` dalla cartella del progetto. I test automatizzati non sostituiscono una prova sulla Station e su Windows.

## Disclaimer

This project is an independent, unofficial, open-source network diagnostic tool. It is not affiliated with, endorsed by, or supported by Vodafone or any router manufacturer.

The software is provided **"AS IS"**, without warranties of any kind, express or implied, to the fullest extent permitted by applicable law.

The authors and contributors make no guarantees regarding accuracy, reliability, compatibility, availability, security, or fitness for any particular purpose.

Network measurements, router logs, and diagnostic results are provided for informational purposes only and should not be considered definitive evidence of network faults.

Users are solely responsible for ensuring that their use of the software is authorized, complies with applicable laws and device terms, and for reviewing any configuration changes they choose to make.

The software may contain bugs or produce incomplete or inaccurate results. Users should take appropriate precautions and maintain backups where necessary.

**To the maximum extent permitted by applicable law, the authors and contributors disclaim liability for damages arising from the use or inability to use this software, including network interruptions, data loss, device malfunction, or other direct or indirect damages.**

See the LICENSE file for the applicable license terms.
