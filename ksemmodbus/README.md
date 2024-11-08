# Modbus Plugin for Kostal Smart Energy Meter

#### Version 1.6.3

This plugin connects your Kostal Smart Energy Meter (https://www.kostal-solar-electric.com/) via ModBus with SmarthomeNG.
- read out all Smart Meter data


## Change history

- support for pymodbus 2 dropped


### Requirements needed software

* Python >= 3.8
* pip install pymodbus
* SmarthomeNG >= 1.8.0

## Configuration

### 1) /smarthome/etc/plugin.yaml

Enable the plugin in plugin.yaml, type in the Smart Meters IP address and configure the ModBus Port and update cycle(seconds).

```yaml
Ksemmodbus:
    plugin_name: ksemmodbus
    ksem_ip: 'XXX.XXX.XXX.XXX'
    modbus_port: '502'
    update_cycle: '20'
```

### 2) /smarthome/items/kostal.yaml

Create an item based on the template files/kostal_item_template.yaml


## Examples

Thats it! Now you can start using the plugin within SmartVisu.
For example:

#### Get data from Energy Meter:
```html
<p>Active Power - : {{basic.value('KSEM_Beszug','Kostal.ksem.ksem_0','W')}} </p>
<p>Active Power + : {{basic.value('KSEM_Einspeisen','Kostal.ksem.ksem_2','W')}} </p>

```


#### The following data are stored in the respective items:

| Addr (dec)        | Description                                       | Format | Unit    |
|-------------------|---------------------------------------------------|--------|---------|
| ksem_0            | Active power+                                     | U32    | W       |
| ksem_2            | Active power-                                     | U32    | W       |
| ksem_4            | Reactive power+                                   | U32    | var     |
| ksem_6            | Reactive power-                                   | U32    | var     |
| ksem_16           | Apparent power+                                   | U32    | VA      |
| ksem_18           | Apparent power-                                   | U32    | VA      |
| ksem_24           | Power factor                                      | Float  | -       |
| ksem_512          | Active energy+                                    | U64    | Wh      |
| ksem_516          | Active energy-                                    | U64    | Wh      |
| ksem_520          | Reactive energy+                                  | U64    | varh    |
| ksem_524          | Reactive energy-                                  | U64    | varh    |
| ksem_544          | Apparent energy+                                  | U64    | VAh     |
| ksem_548          | Apparent energy-                                  | U64    | VAh     |
