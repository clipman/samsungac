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
        debug: false
      - platform: samsung_ac
        config_file: /config/custom_components/samsung_ac/samsung_ac.yaml
        ip_address: 192.168.219.xx   # AC's actual IP (static IP recommended)
        token: "token_extracted_from_the_AC"
        cert: ac14k_m.pem
        name: Bedroom AC
        unique_id: bedroom_aircon
        device_id: "1"
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
    sensors:
      - humidity
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
* read device configuration

## Using
### Default functionality
This component implements the Home Assistant ClimateDevice class. Functionality enabled in HA by default:
* turn device on/off
* select fan mode
* select swing mode
* select target temperatures (min, max and target)
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

