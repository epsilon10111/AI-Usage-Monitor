import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components 3.0 as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    property var usageItems: []
    property bool loaded: false
    property bool hasError: false
    property string errorMessage: ""
    property string debugMessage: ""
    property string updatedAt: "--"
    property int pollIntervalSeconds: Math.max(15, Plasmoid.configuration.pollIntervalSeconds || 60)
    property string configPath: Plasmoid.configuration.configPath || "~/.config/cursor-usage-monitor/config.json"
    readonly property string helperPath: localFilePath(Qt.resolvedUrl("../scripts/cursor_usage_helper.py"))
    readonly property string helperCommand: "python3 " + shellQuote(helperPath) + " --config " + shellQuote(configPath)

    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.title: i18n("Cursor API Monitor")
    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar ? fullRepresentation : compactRepresentation
    Layout.minimumWidth: Kirigami.Units.gridUnit * 11
    Layout.minimumHeight: Kirigami.Units.gridUnit * 4
    Layout.preferredWidth: Kirigami.Units.gridUnit * 16
    Layout.preferredHeight: Kirigami.Units.gridUnit * 9

    function localFilePath(url) {
        var value = String(url)
        if (value.indexOf("file://") === 0) {
            return decodeURIComponent(value.replace("file://", ""))
        }
        return value
    }

    function shellQuote(value) {
        return "'" + String(value).replace(/'/g, "'\\''") + "'"
    }

    function asNumber(value) {
        if (value === null || value === undefined || value === "") {
            return NaN
        }
        var n = Number(value)
        return isNaN(n) ? NaN : n
    }

    function percentFor(item) {
        var explicit = asNumber(item.percent)
        if (!isNaN(explicit)) {
            return Math.max(0, Math.min(100, explicit))
        }

        var used = asNumber(item.used)
        var limit = asNumber(item.limit)
        if (!isNaN(used) && !isNaN(limit) && limit > 0) {
            return Math.max(0, Math.min(100, used / limit * 100))
        }

        return 0
    }

    function formatNumber(value) {
        var n = asNumber(value)
        if (isNaN(n)) {
            return "--"
        }
        if (Math.abs(n - Math.round(n)) < 0.001) {
            return String(Math.round(n))
        }
        return n.toFixed(2).replace(/\.00$/, "")
    }

    function usageText(item) {
        if (!item) {
            return "--"
        }
        if (item.valueText) {
            return item.valueText
        }

        var unit = item.unit ? " " + item.unit : ""
        var used = asNumber(item.used)
        var limit = asNumber(item.limit)
        if (!isNaN(used) && !isNaN(limit)) {
            return formatNumber(used) + " / " + formatNumber(limit) + unit
        }
        if (!isNaN(used)) {
            return formatNumber(used) + unit
        }
        return "--"
    }

    function compactText() {
        if (usageItems.length === 0) {
            return loaded ? "--" : i18n("Loading")
        }
        var parts = []
        for (var i = 0; i < Math.min(2, usageItems.length); i++) {
            parts.push(Math.round(percentFor(usageItems[i])) + "%")
        }
        return parts.join(" / ")
    }

    function statusColor(item) {
        if (!item || item.status === "ok") {
            return Kirigami.Theme.positiveTextColor
        }
        if (item.status === "critical") {
            return Kirigami.Theme.negativeTextColor
        }
        if (item.status === "warning") {
            return Kirigami.Theme.neutralTextColor
        }
        return Kirigami.Theme.disabledTextColor
    }

    function refresh() {
        executable.connectSource(helperCommand)
    }

    function parsePayload(stdout, stderr) {
        try {
            var payload = JSON.parse(stdout || "{}")
            usageItems = payload.items || []
            loaded = true
            hasError = !payload.ok
            errorMessage = payload.error || ""
            debugMessage = payload.debug || stderr || ""
            updatedAt = payload.updatedAtLocal || payload.updatedAt || "--"
        } catch (error) {
            loaded = true
            hasError = true
            usageItems = []
            errorMessage = i18n("Cannot parse helper output")
            debugMessage = String(error) + "\n" + (stdout || "") + "\n" + (stderr || "")
        }
    }

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"

        onNewData: function(sourceName, data) {
            root.parsePayload(data["stdout"], data["stderr"])
            disconnectSource(sourceName)
        }
    }

    Timer {
        interval: root.pollIntervalSeconds * 1000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    Component.onCompleted: root.refresh()

    compactRepresentation: MouseArea {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 5
        Layout.minimumHeight: Kirigami.Units.gridUnit * 2
        onClicked: root.expanded = !root.expanded

        RowLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "utilities-system-monitor"
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.compactText()
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    fullRepresentation: Item {
        implicitWidth: Kirigami.Units.gridUnit * 16
        implicitHeight: Kirigami.Units.gridUnit * 9

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "utilities-system-monitor"
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: Kirigami.Units.iconSizes.smallMedium
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: i18n("Cursor API Usage")
                    font.bold: true
                    elide: Text.ElideRight
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "view-refresh"
                    display: PlasmaComponents3.AbstractButton.IconOnly
                    text: i18n("Refresh")
                    onClicked: root.refresh()
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: root.loaded
                text: root.hasError && root.errorMessage ? root.errorMessage : i18n("Updated: %1", root.updatedAt)
                color: root.hasError ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.disabledTextColor
                font: Kirigami.Theme.smallFont
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: !root.loaded
                text: i18n("Loading usage data...")
                color: Kirigami.Theme.disabledTextColor
            }

            Repeater {
                model: root.usageItems

                delegate: ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing / 2

                    property var item: modelData

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Rectangle {
                            width: Kirigami.Units.smallSpacing
                            height: Kirigami.Units.gridUnit
                            radius: width / 2
                            color: root.statusColor(item)
                        }

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: item.name || i18n("Usage")
                            elide: Text.ElideRight
                        }

                        PlasmaComponents3.Label {
                            text: root.usageText(item)
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: Boolean(item.detail)
                        text: item.detail || ""
                        color: Kirigami.Theme.disabledTextColor
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                    }

                    PlasmaComponents3.ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: root.percentFor(item)
                    }
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: root.loaded && root.usageItems.length === 0 && !root.hasError
                text: i18n("No usage sources configured")
                color: Kirigami.Theme.disabledTextColor
                wrapMode: Text.WordWrap
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.hasError && Plasmoid.configuration.showDebugDetails && root.debugMessage
                text: root.debugMessage
                color: Kirigami.Theme.disabledTextColor
                font: Kirigami.Theme.smallFont
                wrapMode: Text.WordWrap
                maximumLineCount: 6
                elide: Text.ElideRight
            }

            Item {
                Layout.fillHeight: true
            }
        }
    }
}
