# Proxmox VE by Lutarym

Home-Assistant-Integration für Proxmox VE. Überwacht Nodes, virtuelle Maschinen, LXC-Container und Storages und erlaubt das Steuern von Gästen.

## Wie aktuell sind die Daten?

Die Proxmox-API kennt keinen Push-Mechanismus für Ressourcendaten. Es gibt keinen WebSocket und kein Event-Abo, über das Proxmox von sich aus Werte an Home Assistant meldet. Diese Integration fragt die Werte deshalb in einem festen Intervall ab (Polling).

Standardintervall: 30 Sekunden, einstellbar zwischen 5 und 3600 Sekunden.

Das bedeutet konkret:

* Ein Statuswechsel einer VM erscheint in Home Assistant im Schnitt nach einem halben Intervall, spätestens nach einem vollen.
* Nach einem Druck auf einen Steuer-Button wird sofort neu abgefragt, der Zustand aktualisiert sich also ohne Wartezeit.
* Die CPU-Werte, die Proxmox liefert, sind bereits gemittelte Werte aus dem RRD-System von Proxmox, keine Momentaufnahmen. Ein sehr kurzes Abfrageintervall erhöht die Genauigkeit dieser Werte daher nicht, sondern nur die Last auf dem Proxmox-Host.

Unter 10 Sekunden ist selten sinnvoll.

## Installation

### Über HACS

1. HACS öffnen, oben rechts das Menü, dann *Benutzerdefinierte Repositories*
2. URL `https://github.com/lutarym/ha-proxmox` eintragen, Kategorie *Integration*
3. *Proxmox VE by Lutarym* suchen und installieren
4. Home Assistant neu starten

### Manuell

Den Ordner `custom_components/lutarym_proxmox` in das eigene `config`-Verzeichnis kopieren, sodass der Pfad `config/custom_components/lutarym_proxmox/manifest.json` existiert. Danach Home Assistant neu starten.

## API-Token in Proxmox anlegen

Ein Token ist einem Passwort vorzuziehen, weil damit kein Ticket-Refresh nötig ist und die Rechte eng begrenzt werden können.

1. In Proxmox unter *Datacenter, Permissions, Users* einen Benutzer anlegen, zum Beispiel `homeassistant` im Realm `pve`
2. Unter *Datacenter, Permissions, API Tokens* auf *Add*, den Benutzer wählen und eine Token-ID vergeben, zum Beispiel `ha`
3. *Privilege Separation* abwählen, sonst erbt der Token keine Rechte
4. Das angezeigte Secret sofort kopieren, es wird nur einmal angezeigt
5. Unter *Datacenter, Permissions* dem Benutzer auf dem Pfad `/` die Rolle `PVEAuditor` zuweisen

`PVEAuditor` reicht für das reine Auslesen. Für die Steuer-Buttons wird zusätzlich `VM.PowerMgmt` benötigt.

## Einrichtung in Home Assistant

Unter *Einstellungen, Geräte und Dienste, Integration hinzufügen* nach *Proxmox VE by Lutarym* suchen. Die Einrichtung läuft in drei Schritten.

### Schritt 1, Verbindung

| Feld | Bedeutung | Standard |
| --- | --- | --- |
| Host | IP oder Hostname, ohne `https://` | |
| Port | Port der Proxmox-Weboberfläche | 8006 |
| Benutzername | ohne Realm, also `homeassistant` statt `homeassistant@pve` | |
| Realm | `pam` für lokale Systembenutzer, `pve` für in Proxmox angelegte Benutzer | pam |
| Anmeldung | API-Token oder Passwort | API-Token |
| Token-ID und Token-Secret | bei Anmeldung per Token | |
| Passwort | bei Anmeldung per Passwort | |
| SSL-Zertifikat prüfen | bei selbstsigniertem Zertifikat abwählen | an |
| Zeitüberschreitung | Sekunden, die auf eine Antwort gewartet wird, bevor ein Abruf als fehlgeschlagen gilt. Bei entfernten oder stark ausgelasteten Hosts erhöhen. | 20 s |

### Schritt 2, Ressourcen

Die Integration liest alle vorhandenen Nodes, VMs, Container und Storages aus.

| Feld | Bedeutung | Standard |
| --- | --- | --- |
| Nodes, VMs, Container, Storages | Nur die angehakten Ressourcen werden abgefragt und als Geräte angelegt. | alle |
| Neue Ressourcen automatisch aufnehmen | Siehe nächster Abschnitt. | an |
| Templates einbeziehen | VM- und Container-Templates laufen nie und melden keine Auslastung, ihre Sensoren blieben leer. | aus |

### Schritt 3, Abfrage und Aufräumen

| Feld | Bedeutung | Standard | Bereich |
| --- | --- | --- | --- |
| Abfrageintervall | Sekunden zwischen zwei Abfragen. Bestimmt die Aktualität, siehe oben. | 30 s | 5 bis 3600 |
| Verschwundene Ressourcen vorhalten | Tage bis zum Löschen, siehe übernächster Abschnitt. | 14 d | 0 bis 365 |
| Steuer-Buttons anlegen | Start, Stopp und Neustart für VMs und Container. Braucht das Recht `VM.PowerMgmt`. Bei einem reinen Lese-Token abschalten. | an | |
| Node-Details abrufen | Liefert Last, IO-Wartezeit, Swap, Root-Dateisystem und Kernel-Version. Kostet je Node und Zyklus einen zusätzlichen API-Aufruf. Bei großen Clustern abschalten. | an | |
| Zeitfenster fehlgeschlagener Tasks | Stunden, die der Sensor für fehlgeschlagene Tasks zurückblickt. | 24 h | 1 bis 720 |

### Später ändern

Alles außer den Verbindungsdaten lässt sich über *Konfigurieren* an der Integration ändern. Dort erscheint ein Menü mit den beiden Bereichen *Ressourcen* und *Abfrage und Aufräumen*. Nach dem Speichern lädt die Integration neu.

Die Verbindungsdaten selbst werden über *Erneut anmelden* geändert, was Home Assistant auch von sich aus anbietet, sobald Proxmox die Zugangsdaten ablehnt.

Schaltest du *Steuer-Buttons anlegen* nachträglich ab, verschwinden die vorhandenen Buttons nicht sofort aus der Registry, sondern werden als nicht verfügbar angezeigt. Sie lassen sich dort von Hand löschen.

## Neue und gelöschte VMs

Legst du in Proxmox eine neue VM, einen Container, einen Node oder einen Storage an, erscheinen die zugehörigen Entitäten beim nächsten Abruf von selbst. Kein Neustart, kein Neuladen der Integration nötig. Bei einem Intervall von 30 Sekunden dauert es also höchstens eine halbe Minute.

Verschwindet eine Ressource, wird ihr Gerät nicht sofort gelöscht, sondern zunächst nur vorgemerkt. Erst wenn sie die eingestellte Vorhaltezeit lang nicht zurückkehrt, werden Gerät und Entitäten entfernt. Standard sind 14 Tage, einstellbar zwischen 0 und 365.

Damit überstehen eine Migration auf einen anderen Node, eine Wiederherstellung aus dem Backup oder eine längere Wartung die Abwesenheit, ohne dass die Verlaufsdaten und die Zugehörigkeit zu Automationen verloren gehen. Kehrt die Ressource innerhalb der Frist zurück, wird die Vormerkung aufgehoben und die Entitäten sind einfach wieder verfügbar.

Die Frist wird im Speicher von Home Assistant abgelegt und läuft über einen Neustart hinweg weiter. Ein Neustart verlängert sie also nicht. Welche Ressourcen gerade vorgemerkt sind und wie viele Tage ihnen bleiben, steht im Diagnose-Export unter `pending_removal`.

Schlägt ein Abruf fehl, etwa weil der Proxmox-Host gerade neu startet, wird weder vorgemerkt noch gelöscht. Nur ein erfolgreicher Abruf, der die Ressource nicht mehr enthält, startet die Frist.

Auf 0 gesetzt wird sofort beim ersten erfolgreichen Abruf ohne die Ressource gelöscht.

Das Verhalten steuert der Schalter *Neue Ressourcen automatisch aufnehmen*:

**Eingeschaltet, Standard.** Was du in der Auswahl abwählst, wird dauerhaft ausgeschlossen. Alles andere wird überwacht, auch später Angelegtes. Willst du eine bestimmte VM nicht sehen, hake sie unter *Konfigurieren* ab, dann verschwindet ihr Gerät beim nächsten Abruf.

**Ausgeschaltet.** Nur die ausdrücklich angehakten Ressourcen werden überwacht. Eine neue VM bleibt unsichtbar, bis du sie unter *Konfigurieren* dazunimmst. Sinnvoll, wenn auf dem Host regelmäßig kurzlebige VMs entstehen, die Home Assistant nicht sehen soll.

Ist eine VM nach Ablauf der Vorhaltezeit entfernt worden und taucht später unter derselben VMID wieder auf, wird sie als neue Ressource behandelt und bekommt frische Entitäten.

## Entitäten

### Node

CPU, CPU-Kerne, Arbeitsspeicher in Prozent und Byte, Festplatte in Prozent und Byte, Last über 1, 5 und 15 Minuten, IO-Wartezeit, Swap, Root-Dateisystem, Kernel-Version, Proxmox-Version, letzter Start, Online-Status.

### Virtuelle Maschine und Container

CPU, CPU-Kerne, Arbeitsspeicher in Prozent und Byte, Festplatte in Prozent und Byte, gelesene und geschriebene Datenmenge, empfangene und gesendete Netzwerkdatenmenge, letzter Start, Status als Text, Laufzustand.

### Storage

Belegung in Prozent, belegt, frei, gesamt, Problemmelder.

### Cluster

Fehlgeschlagene Tasks der letzten 24 Stunden, mit den letzten zehn Fehlern als Attribut.

### Steuerung

Für VMs: Start, Herunterfahren, Stopp, Neustart, Reset, Anhalten, Fortsetzen.
Für Container: Start, Herunterfahren, Stopp, Neustart.

Buttons werden ausgeblendet, wenn sie im aktuellen Zustand keinen Sinn ergeben. Der Start-Button ist bei einer laufenden VM nicht bedienbar, der Stopp-Button bei einer gestoppten. Templates bekommen keine bedienbaren Buttons.

Einige Entitäten sind bewusst deaktiviert angelegt, etwa Reset und Anhalten sowie die Gesamtgrößen. Sie lassen sich in den Entitätseinstellungen aktivieren.

## Bekannte Einschränkungen

* **Festplattenbelegung von QEMU-VMs ist immer 0.** Proxmox kennt die Belegung innerhalb einer VM nicht, solange der QEMU-Guest-Agent keine Daten liefert. Das ist ein Verhalten der Proxmox-API, kein Fehler der Integration. Bei LXC-Containern und Storages ist der Wert korrekt.
* **Netzwerk- und Datenträgerzähler springen auf 0 zurück**, wenn ein Gast neu startet. Die Zähler laufen ab dem Start des Gastes, nicht ab dem Start des Hosts. Die Sensoren sind deshalb als `total_increasing` deklariert, damit die Statistik in Home Assistant den Rücksetzer korrekt behandelt.
* **Temperaturen und S.M.A.R.T.-Werte** werden nicht ausgelesen. Beides ist über die API nur mit erhöhten Rechten und je nach Hardware unzuverlässig verfügbar.
* Ein Node, der offline ist, liefert keinen Detailstatus. Last, Swap und Kernel-Version stehen dann auf *nicht verfügbar*, die Grundwerte aus der Clusterabfrage bleiben erhalten.

## Fehlersuche

**Zugangsdaten abgelehnt.** Benutzername ohne Realm eintragen und den Realm separat wählen. Prüfen, ob bei der Token-Erstellung *Privilege Separation* abgewählt wurde, und ob dem Benutzer eine Rolle auf dem Pfad `/` zugewiesen ist.

**Server nicht erreichbar.** Bei selbstsigniertem Zertifikat *SSL-Zertifikat prüfen* abwählen. Port kontrollieren, Standard ist 8006.

**Buttons reagieren nicht.** Dem Benutzer fehlt `VM.PowerMgmt`. Mit `PVEAuditor` allein ist nur Lesen möglich.

**Keine Werte.** Unter *Konfigurieren* prüfen, ob die betreffende Ressource ausgewählt ist.

Für Fehlermeldungen hilft der Diagnose-Export an der Integration. Zugangsdaten sind darin maskiert.

## Tests

Im Ordner `tests` liegen fünf Skripte, die die Integration gegen einen simulierten Proxmox-Server prüfen, ohne dass ein echter Server nötig ist.

```
python3 -m venv .venv
.venv/bin/pip install homeassistant proxmoxer
.venv/bin/python tests/test_integration.py
.venv/bin/python tests/test_entities.py
.venv/bin/python tests/test_dynamic.py
.venv/bin/python tests/test_grace.py
.venv/bin/python tests/test_options.py
```

Geprüft werden unter anderem der Aufbau der API-Aufrufe, die Datenaufbereitung, das Wirken von Einschluss- und Ausschlussliste, die Berechnung aller Sensorwerte inklusive Randfällen, die Eindeutigkeit der Entitäts-IDs, die Zuordnung von HTTP-Fehlern und die Vollständigkeit beider Übersetzungen.

`test_dynamic.py` deckt das Nachlegen ab: neue VM, neuer Container, neuer Node, neuer Storage, kein doppeltes Anlegen bei wiederholten Abrufen, und dass bei einem fehlgeschlagenen Abruf nichts angelegt wird.

`test_options.py` deckt die Einrichtungsparameter ab: dass jedes Feld in einem der drei Schritte auftaucht, keines doppelt abgefragt wird, jeder Standardwert innerhalb seiner Grenzen liegt, bestehende Werte korrekt vorbelegt werden, Secrets nie vorbelegt werden, und dass jeder Schalter messbar wirkt, etwa der Detailabruf an der Zahl der API-Aufrufe.

`test_grace.py` deckt die Vorhaltezeit ab, mit gestellter Uhr: Vormerkung beim Verschwinden, kein Löschen kurz vor Ablauf, Löschen nach Ablauf, Rückkehr innerhalb der Frist, Weiterlaufen der Frist über einen Neustart, sofortiges Löschen bei 0 Tagen, und dass eine gestörte Verbindung nichts auslöst.

## Voraussetzungen

Home Assistant ab 2024.11, Proxmox VE 7 oder 8, `proxmoxer` 2.3.0 wird automatisch installiert.

## Lizenz

MIT
