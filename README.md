[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

# Samsung AC - Local IP based climate device for Home Assistant
Implementation of ClimateDevice for controlling Samsung air conditioners locally over IP, without going through the SmartThings cloud API.

This component works with Samsung AC units available at port 8888 (new generation, local REST API).

Support for any unit working with a similar local REST API can be easily added via a YAML configuration file.

This component was created by SebuZet, he however appears to be MIA so I have forked and repaired his component
https://github.com/SebuZet/samsungrac

## Installation
1. Download all files from repo to newly created folder
2. Move folder `custom_components/samsung_ac` to your `<ha_configuration_folder>`
3. In __configuration.yaml__ file add section:
    ```yaml
    climate:
      - platform: samsung_ac
        config_file: /config/custom_components/samsung_ac/samsung_ac.yaml
        ip_address: 192.168.219.xx   # AC's actual IP (static IP recommended)
        token: "token_extracted_from_the_AC"
        cert: ac14k_m.pem
        name: Living Room AC
        unique_id: livingroom_aircon
        device_id: "0"
        humidity_refresh_interval: 600

      - platform: samsung_ac
        config_file: /config/custom_components/samsung_ac/samsung_ac.yaml
        ip_address: 192.168.219.xx   # AC's actual IP (static IP recommended)
        token: "token_extracted_from_the_AC"
        cert: ac14k_m.pem
        name: Bedroom AC
        unique_id: bedroom_aircon
        device_id: "1"
        humidity_refresh_interval: 0
    ```

## Sensors (air quality / filter status)
In addition to the `climate` platform, this component also provides a `sensor` platform that exposes read-only values reported by the AC (indoor humidity, filter clean level, odor level, PM10, PM2.5) as separate Home Assistant sensor entities. It reuses the same YAML config file and the same local connection as the `climate` platform, so no extra credentials are needed.

```yaml
sensor:
  - platform: samsung_ac
    ip_address: 192.168.219.8
    token: XXXXrz6771
    cert: ac14k_m.pem
    name: Livingroom AC
    unique_id: livingroom_aircon
    device_id: "0"
    sensors:
      - humidity
      - clean_level
      - odor_level
      - pm10
      - pm2_5

  - platform: samsung_ac
    ip_address: 192.168.219.8
    token: XXXXrz6771
    cert: ac14k_m.pem
    name: Bedroom AC
    unique_id: bedroom_aircon
    device_id: "1"
```

| Parameter        | description           |  Required        |
| ------------- |-------------|-------------|
| ip_address      | Device IP address |Yes
| token           | Access token gathered from the device |Yes
| cert   | certificate file name (default: ac14k_m.pem) | Usually Yes
| name      | Device name, used as a prefix for each sensor's friendly name | No
| unique_id | Base unique ID; each sensor appends its key (e.g. `_humidity`) | No
| device_id | Device ID on the hub, for controllers that can manage multiple units | No
| sensors   | List of sensor keys to create. Omit to create all available ones: `clean_level`, `odor_level`, `pm10`, `pm2_5`, `humidity` | No
| debug     | Enable/disable more debugs. Default: False | No

If you have multiple AC units connected to the same hub, add one `sensor` block per unit (as shown above), each with its own `device_id` and `unique_id`.

## Configuration
1. Configuration parameters:

    | Parameter        | description           |  Required        |
    | ------------- |-------------|-------------|
    | config_file      | YAML configuration filename |Yes
    | ip_address      | Device IP address (e.g. 192.178.1.200) |Yes
    | token           | Access token gathered from the device        |Yes
    | cert_file   | certificate file name (default: ac14k_m.pem, use __None__ to skip certificate verification) | Usually Yes
    | name      | Device name (by default this value is taken from YAML config file) | No
    | unique_id | Unique ID for the entity. Recommended when running multiple AC units, so HA doesn't have to derive one automatically | No
    | device_id | Device ID on the hub, for controllers that can manage multiple units. Defaults to `032000000` | No
    | controller    | Controller type to use (default, and the only one for now: yaml)  | No
    | humidity_refresh_interval | How often (in seconds) the `climate` entity automatically triggers an on-demand humidity/air-quality reading (see [Humidity reading](#humidity-reading) below). Runs once immediately on startup, then repeats on this interval. Default: `600` (10 minutes). Set to `0` to disable automatic refreshing entirely (e.g. for units without a humidity sensor). | No
    | debug      | Enable/disable more debugs. Default: False | No
2. You need to have your device __token__. I will create a guide to gather it
3. YAML configuration
You can easily add, remove or modify any device parameter to meet device capabilities.

## YAML configuration file syntax
```yaml
climate:
  - platform: samsung_ac
    config_file: samsung_ac.yaml
    ip_address: 192.168.219.8
    token: XXXXrz6771
    cert: ac14k_m.pem
    name: Livingroom AC
    unique_id: livingroom_aircon
    device_id: "0"
    debug: false
```
## Functionality
Functionality depends on the yaml configuration file and can be easily changed by editing it. Currently the configuration provides:
* turn device on and off
* sets and reads target/min/max temperatures
* sets and reads swing direction
* sets and reads fan level
* sets and reads fan maximum level
* sets and reads special mode (2Step, Comfort, Quiet etc)
* sets and reads good sleep mode
* turn purify mode on and off
* turn auto clean mode on and off
* turn beep mode on and off
* read current indoor temperature
* read current indoor humidity (on-demand refresh, see [Humidity reading](#humidity-reading))
* read device configuration

## Using
### Default functionality
This component implements the Home Assistant ClimateDevice class. Functionality enabled in HA by default:
* turn device on/off
* select fan mode
* select swing mode
* select target temperatures (min, max and target)

### Humidity reading
Samsung units only measure indoor humidity on-demand, not continuously - except while in **Dry** mode, where a live value is reported automatically. Outside of Dry mode, the `climate` entity's `current_humidity` attribute (and the standalone `sensor.humidity` entity, if configured) will otherwise sit at a stale or `0` value until a reading is explicitly requested.

To handle this automatically, the `climate` entity periodically triggers a fresh reading in the background:
* Runs once immediately when the entity loads/reloads, then every `humidity_refresh_interval` seconds (default `600`, i.e. 10 minutes).
* Skipped while the unit is `off` or already in `Dry` mode, since neither case needs the nudge.
* Set `humidity_refresh_interval: 0` to disable this entirely - useful for units that don't have a humidity sensor at all.

You can also trigger a reading manually (e.g. from an automation or the Developer Tools > Actions panel) using the **climate.samsung_ac_refresh_humidity** service:
```yaml
action: climate.samsung_ac_refresh_humidity
data:
  entity_id: climate.livingroom_aircon
```
Omit `entity_id` to refresh all configured `samsung_ac` climate entities at once.

### Device specific functions
Device specific functionality is added as extra service called **climate.samsung_ac_set_property**.
Every device attribute can be set using this service with proper params.

```
{
  "entity_id" : "climate.salon_ac",
  "power" : "on",
  "purify" : "on",
  "special_mode" : "comfort"
}
```
### Switches for special functions
To make controlling the device as easy as possible, users can create template switches for operations defined as __Switch__ (please see configuration file).
Below is an example of a template switch for the Purify option
```
switch:
  - platform: template
    switches:
      purify:
        value_template: "{{ is_state_attr('climate.salon_ac', 'purify', 'on') }}"
        turn_on:
          action: samsung_ac.samsung_ac_set_property
          data:
            entity_id: climate.salon_ac
            purify: 'on'
        turn_off:
          action: samsung_ac.samsung_ac_set_property
          data:
            entity_id: climate.salon_ac
            purify: 'off'
```
# References
 * [Samsung protocol description](https://community.openhab.org/t/newgen-samsung-ac-protocol/33805)
 * [HA forum](https://community.home-assistant.io/t/samsung-ac/11747/11)

## TODO
Documentation...

## Known issues

### Noisy `urllib3.connection` header-parsing warnings

The AC's local REST API sends a slightly malformed `X-API-Version` header
(a stray space before the colon), which trips up Python 3.14's stricter
header parsing in `urllib3`. This doesn't affect functionality, but it can
flood your Home Assistant log with entries like:

```
Logger: urllib3.connection
Failed to parse headers (url=https://192.168.219.8:8888/devices): [MissingHeaderBodySeparatorDefect()], unparsed data: 'X-API-Version : v1.0.0\r\n\r\n'
```

To silence just this logger without hiding other useful logs, add the
following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    urllib3.connection: fatal
```
