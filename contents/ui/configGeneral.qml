import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components 3.0 as PlasmaComponents3

Kirigami.FormLayout {
    id: page

    property alias cfg_configPath: configPath.text
    property alias cfg_pollIntervalSeconds: pollInterval.value
    property alias cfg_showDebugDetails: showDebugDetails.checked

    PlasmaComponents3.TextField {
        id: configPath
        Kirigami.FormData.label: i18n("Config file:")
        placeholderText: "~/.config/cursor-usage-monitor/config.json"
        Layout.fillWidth: true
    }

    PlasmaComponents3.SpinBox {
        id: pollInterval
        Kirigami.FormData.label: i18n("Refresh every:")
        from: 15
        to: 3600
        stepSize: 15
        editable: true
        textFromValue: function(value) {
            return i18n("%1 seconds", value)
        }
        valueFromText: function(text) {
            return parseInt(text, 10)
        }
    }

    PlasmaComponents3.CheckBox {
        id: showDebugDetails
        Kirigami.FormData.label: i18n("Debug:")
        text: i18n("Show helper error details")
    }
}
