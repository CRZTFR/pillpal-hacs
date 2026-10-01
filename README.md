# Pill Pal for Home Assistant

Connects a Pill Pal lamp to Home Assistant over your home network. Home Assistant can
switch and colour the ambient light, show notifications, statuses and gauges on the lamp,
acknowledge or snooze a reminder, and run automations when someone touches the lamp.

Reminders themselves stay in the Bindicator app. Home Assistant cannot create, change or
delete them, and the lamp refuses it if asked.

## Tested with

| Part | Version |
| --- | --- |
| This integration | 0.2.0 |
| Home Assistant | 2026.2.3 |
| Lamp firmware | 2026.09.30.3 |

Home Assistant 2025.1 is the oldest release HACS will install this on. Older releases
than the one above have not been tried.

## Before you start

- Set the lamp up in the Bindicator app and connect it to Wi-Fi.
- Home Assistant has to be on the same network as the lamp. It does not need the
  internet to control the lamp.
- [HACS](https://hacs.xyz) has to be installed in Home Assistant.

## Install

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=CRZTFR&repository=pillpal-hacs&category=integration)

1. In HACS, add `https://github.com/CRZTFR/pillpal-hacs` as a custom repository of type
   Integration, then install Pill Pal. The button above does this for you.
2. Restart Home Assistant.
3. Home Assistant finds the lamp on its own and offers it under Settings > Devices &
   services. If it does not, choose Add integration > Pill Pal and enter the lamp's
   address. The Bindicator app shows the address in Setup, under Connection and phones.
4. Home Assistant shows a six-digit code. Open the Bindicator app on a phone that
   controls the lamp and approve Home Assistant. Check the app shows the same code
   first. If the codes differ, decline: something on your network is between Home
   Assistant and the lamp.

The request waits 10 minutes. You do not need to touch the lamp.

Adding Home Assistant does not change the lamp's Wi-Fi, reminders or phones.

## What you get

All entities belong to one device per lamp, named Pill Pal. The entity IDs below are for
the first lamp; a second lamp gets `_2` on the end.

| Entity | What it does |
| --- | --- |
| Ambient light (`light.pill_pal_ambient_light`) | On, off, brightness, colour, and the built-in scenes as effects |
| Touch (`event.pill_pal_touch`) | An event for every tap, double tap and long press, with what the lamp was showing and what it did |
| Next reminder (`sensor.pill_pal_next_reminder`) | When the next reminder is due |
| Reminders showing (`sensor.pill_pal_reminders_showing`) | How many reminders are signalling now, listed in its attributes |
| Statuses (`sensor.pill_pal_statuses`) | How many statuses are set, listed in its attributes with who set each one |
| Gauge (`sensor.pill_pal_gauge`) | The gauge level as a percentage, with its colours, whether it is stale, and who set it |
| Notification (`binary_sensor.pill_pal_notification`) | On while a notify is playing, with its pattern, colour, end time and who sent it |
| Last reminder (`sensor.pill_pal_last_reminder`) | Done, missed or snoozed, for the most recent reminder that was acted on or ran out, with its name and time |
| Wi-Fi signal | A diagnostic, off until you turn it on |

Indicators and reminder actions from any controller appear here, not only the ones Home
Assistant sent. A gauge set in the app, or a reminder acknowledged at the lamp, shows up
the same way.

The scenes are warm white, candle, sunrise, candy floss, lavender, ocean, aurora, forest
and sherbet. A colour chosen in the app or with `rgb_color` shows no effect.

### Touch attributes

| Attribute | Values |
| --- | --- |
| `event_type` | `tap`, `double_tap`, `long_press` |
| `mode` | What was on top when the touch landed: `idle`, `status`, `reminder`, `notify` |
| `action` | What the lamp did: `toggle_ambient`, `next_scene`, `acknowledge`, `snooze`, `acknowledge_status`, `dismiss_notify`, `undo`, `event_only` (bound to nothing) or `none` (nothing to act on) |
| `pad` | `0` or `1`, which of the two touch pads |
| `occurrence_id` | The reminder the touch acted on, if any |
| `status_id`, `status_owner` | The status the touch acted on, if any |

A long press is a touch held for 1 to 3 seconds. It does nothing on the lamp itself, so
it is free for automations. Holding for longer than 3 seconds sends nothing. The
10-second pairing hold and anything else to do with access to the lamp is never sent.

### Reminders showing attributes

`reminders` lists each reminder that is signalling, with `occurrence_id`, `name`, `due_at`
and `ends_at`. `touch_target` is the occurrence a tap on the lamp would act on now, which
is the earliest one due. Pass these IDs to `pill_pal.acknowledge` and `pill_pal.snooze`.

## Actions

Every action needs `device_id`, the lamp. In the automation editor, pick the lamp from the
list; in YAML, the editor's YAML view shows the ID it chose.

| Action | Fields |
| --- | --- |
| `pill_pal.notify` | `pattern`: `flash`, `pulse`, `sweep` or `rainbow`. `color`: RGB, white if left out, not used by rainbow. `duration`: 1 to 60 seconds, default 5. |
| `pill_pal.set_status` | `status_id`: up to 23 letters, numbers, dots, dashes or underscores. `color`: RGB. `pattern`: `solid` or `pulse`. `brightness`: 1 to 255. `label`: up to 47 characters, shown in the app. `priority`: `low`, `normal` or `high`. `clears_at`: optional date and time when the lamp clears it by itself. |
| `pill_pal.clear_status` | `status_id`. Clearing a status that is not set does nothing. |
| `pill_pal.set_gauge` | `value`: 0 to 1. `color`: RGB at the empty end. `color_end`: optional RGB at the full end. `stale_after`: 60 to 86,400 seconds, default 900. |
| `pill_pal.clear_gauge` | Nothing else. |
| `pill_pal.acknowledge`, `pill_pal.snooze` | `occurrence_id`, from the Reminders showing or Touch attributes. A snooze lasts 10 minutes. |

How they behave on the lamp:

- A notify plays over everything, including a reminder, and then the lamp goes back to
  what it was showing. A touch stops it early.
- A status stays until it is cleared, through lamp and Home Assistant restarts. A tap dims
  it without clearing it, and setting the same ID again keeps it dimmed. A set after a
  clear shows it at full strength again.
- A lamp holds eight statuses in all, from every controller. A ninth is refused with
  `status_full`. Reminders always come first: a status that does not fit is kept and shown
  when there is room.
- The gauge fills from one end of the lamp, by the lamp's "Fill from the other end"
  setting in the app. With no new value for `stale_after` seconds, it dims and breathes
  so an old reading does not look current.
- Acknowledge and snooze act on that one reminder only. Home Assistant cannot create,
  change or delete reminders.

## Blueprints

Each blueprint below imports into Home Assistant with one click, then asks for the lamp
and the entity to use.

| Blueprint | What it does | Import |
| --- | --- | --- |
| [Play a pattern when something happens](blueprints/automation/pill_pal/notify_when.yaml) | A notify when an entity changes to a state, such as a washing machine finishing | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCRZTFR%2Fpillpal-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpill_pal%2Fnotify_when.yaml) |
| [Show a status while something is true](blueprints/automation/pill_pal/status_while.yaml) | A status while an entity is in a state, such as a door open, cleared when it changes back and checked again after a restart | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCRZTFR%2Fpillpal-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpill_pal%2Fstatus_while.yaml) |
| [Show a sensor on the gauge](blueprints/automation/pill_pal/gauge_from_sensor.yaml) | Fills the lamp in proportion to a sensor between a low and a high mark, such as solar export | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCRZTFR%2Fpillpal-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpill_pal%2Fgauge_from_sensor.yaml) |
| [Do something when the lamp is touched](blueprints/automation/pill_pal/touch_action.yaml) | Runs your actions on a long press, tap or double tap, optionally only while a status or reminder is showing | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCRZTFR%2Fpillpal-hacs%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpill_pal%2Ftouch_action.yaml) |

## Examples in YAML

The same ideas written out, to paste into an automation's YAML view. Replace
`YOUR_LAMP_DEVICE_ID` with the lamp's device ID.

A pattern when the washing machine finishes:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.washing_machine
    to: finished
    not_from: [unavailable, unknown]
actions:
  - action: pill_pal.notify
    data:
      device_id: YOUR_LAMP_DEVICE_ID
      pattern: pulse
      color: [0, 120, 255]
      duration: 10
```

A status while the garage door is open, cleared when it closes. The start trigger puts
the lamp right after Home Assistant restarts:

```yaml
triggers:
  - trigger: state
    entity_id: cover.garage_door
  - trigger: homeassistant
    event: start
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

Solar export on the gauge, from a sensor that already reads 0 to 1:

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

Turn on the hallway light when someone long-presses the lamp. The first condition skips
the lamp coming back online, which also changes the entity:

```yaml
triggers:
  - trigger: state
    entity_id: event.pill_pal_touch
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none
         and trigger.from_state.state != 'unavailable'
         and trigger.to_state.state not in ['unavailable', 'unknown'] }}
  - condition: state
    entity_id: event.pill_pal_touch
    attribute: event_type
    state: long_press
actions:
  - action: light.toggle
    target:
      entity_id: light.hallway
```

Acknowledge the reminder the lamp is pointing at, from a button on a dashboard or a
script:

```yaml
- condition: template
  value_template: "{{ state_attr('sensor.pill_pal_reminders_showing', 'touch_target') is not none }}"
- action: pill_pal.acknowledge
  data:
    device_id: YOUR_LAMP_DEVICE_ID
    occurrence_id: "{{ state_attr('sensor.pill_pal_reminders_showing', 'touch_target') }}"
```

## Restarts and outages

- Everything here works over your home network. If the internet goes down, Home
  Assistant still controls the lamp.
- Statuses survive a lamp restart and a Home Assistant restart. An automation that sets
  and clears by the same ID, and runs again when Home Assistant starts, keeps the lamp
  right either way.
- A notify is never queued. If the lamp is unreachable, the action fails with "Could not
  reach the lamp."
- If the lamp gets a new address on your network, Home Assistant follows it.

## Disconnecting

Remove Home Assistant in the app under Setup, or delete the integration in Home
Assistant. Either way, the lamp keeps its reminders, Wi-Fi and phones. Removing it in the
app also clears the statuses Home Assistant set, and the gauge if Home Assistant set it.

A lamp that is reset forgets Home Assistant. Home Assistant then asks you to approve it
again, with a new code.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| The lamp is not offered under Devices & services | Some routers block discovery between devices. Add it by hand with Add integration > Pill Pal and the lamp's address from the app. |
| No request appears in the app | The phone has to reach the lamp, at home or through the internet. Open the lamp in the app and wait a few seconds. The request lasts 10 minutes; start again in Home Assistant if it ran out. |
| "The lamp no longer accepts Home Assistant" | Home Assistant was removed in the app, or the lamp was reset. Home Assistant asks to re-authenticate the lamp under Settings > Devices & services. Start that, then approve the new code in the app. |
| "The lamp refused the command: status_full" | Eight statuses are set. Clear one you no longer need. |
| "Could not reach the lamp" | Check the lamp has power and is on Wi-Fi. The entities show unavailable until it is back. |
| A gauge looks dim and breathes | No value has arrived for longer than `stale_after`. Check the automation that sets it is still running. |

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
