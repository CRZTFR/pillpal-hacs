# Pill Pal for Home Assistant

Connects a Pill Pal lamp to Home Assistant over your home network. Home Assistant can
switch and colour the ambient light, show notifications, statuses and gauges on the lamp,
acknowledge or snooze a reminder, and run automations when someone touches the lamp.

Reminders themselves stay in the Bindicator app. Home Assistant cannot create, change or
delete them, and the lamp refuses it if asked.

## Before you start

Set the lamp up in the Bindicator app and connect it to Wi-Fi. Home Assistant has to be
on the same network as the lamp.

## Install

1. In HACS, add this repository as a custom repository of type Integration, then
   install Pill Pal.
2. Restart Home Assistant.
3. Home Assistant finds the lamp on its own and offers it under Settings > Devices &
   services. If it does not, choose Add integration > Pill Pal and enter the lamp's
   address.
4. Home Assistant shows a six-digit code. Open the Bindicator app on a phone that
   controls the lamp and approve Home Assistant. Check the app shows the same code
   first. If the codes differ, decline: something on your network is between Home
   Assistant and the lamp.

The request waits 10 minutes. You do not need to touch the lamp.

To disconnect, remove Home Assistant in the app, or delete the integration. A lamp that
is reset forgets Home Assistant, and the integration asks you to approve it again.

## What you get

| Entity | What it does |
| --- | --- |
| Ambient light | On, off, brightness, colour, and the built-in scenes as effects |
| Touch | An event for every tap, double tap and long press, with what the lamp was showing and what it did |
| Next reminder | When the next reminder is due |
| Reminders showing | How many reminders are signalling now |
| Statuses | How many statuses are set, listed in its attributes with who set each one |
| Gauge | The gauge level as a percentage, with its colours, whether it is stale, and who set it |
| Notification | On while a notify is playing, with its pattern, colour, end time and who sent it |
| Last reminder | Done, missed or snoozed, for the most recent reminder that was acted on or ran out, with its name and time |

Indicators and reminder actions from any controller appear here, not only the ones Home
Assistant sent. A gauge set in the app, or a reminder acknowledged at the lamp, shows up
the same way.

## Actions

| Action | What it does |
| --- | --- |
| `pill_pal.notify` | Plays flash, pulse, sweep or rainbow for 1 to 60 seconds, then goes back to what was showing. A touch stops it. |
| `pill_pal.set_status` | Shows a status until it is cleared. Setting the same ID again updates it. A tap dims it without clearing it. |
| `pill_pal.clear_status` | Removes a status this integration set. |
| `pill_pal.set_gauge` | Fills the lamp to a value from 0 to 1. With no new value for the stale time (15 minutes by default), it dims and breathes so an old reading does not look current. |
| `pill_pal.clear_gauge` | Removes the gauge. |
| `pill_pal.acknowledge`, `pill_pal.snooze` | Act on one reminder by its occurrence ID. |

A lamp holds eight statuses in all. Reminders always come first: a status that does not
fit is kept and shown when there is room.

## Examples

A pattern when the washing machine finishes:

```yaml
action: pill_pal.notify
data:
  device_id: YOUR_LAMP_DEVICE_ID
  pattern: pulse
  color: [0, 120, 255]
  duration: 10
```

A status while the garage door is open, cleared when it closes:

```yaml
triggers:
  - trigger: state
    entity_id: cover.garage_door
actions:
  - if:
      - condition: state
        entity_id: cover.garage_door
        state: open
    then:
      - action: pill_pal.set_status
        data:
          device_id: YOUR_LAMP_DEVICE_ID
          status_id: garage
          color: [255, 136, 0]
          label: Garage door open
    else:
      - action: pill_pal.clear_status
        data:
          device_id: YOUR_LAMP_DEVICE_ID
          status_id: garage
```

Statuses survive a lamp restart and a Home Assistant restart. An automation like this one
that sets and clears by the same ID keeps the lamp right either way.

Solar export on the gauge:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.solar_export_fraction
actions:
  - action: pill_pal.set_gauge
    data:
      device_id: YOUR_LAMP_DEVICE_ID
      value: "{{ states('sensor.solar_export_fraction') | float(0) }}"
      color: [255, 200, 0]
```

Run something when someone long-presses the lamp:

```yaml
triggers:
  - trigger: state
    entity_id: event.pill_pal_touch
conditions:
  - condition: state
    entity_id: event.pill_pal_touch
    attribute: event_type
    state: long_press
actions:
  - action: light.toggle
    target:
      entity_id: light.hallway
```

## Privacy on your network

Commands are signed with a key only the lamp and Home Assistant hold, so nothing else on
your network can control the lamp. The key is never sent: both sides work it out during
approval. The traffic is not encrypted, so status labels, reminder names and touches can
be read by other devices on the same network.

## Development

```
python3.13 -m venv .venv
.venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```

`tests/fixtures` holds copies of the lamp's contract fixtures, and the tests check the
integration against them. With a lamp on a USB cable, `tests/live` runs the whole path
against it:

```
PILLPAL_HOST=<lamp address> PILLPAL_CONSOLE=/dev/cu.usbmodem1101 .venv/bin/pytest tests/live -s
```
