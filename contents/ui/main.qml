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
    property string configPath: Plasmoid.configuration.configPath || "~/.config/ai-usage-monitor/config.json"
    readonly property string helperPath: localFilePath(Qt.resolvedUrl("../scripts/usage_helper.py"))
    readonly property string helperCommand: "python3 " + shellQuote(helperPath) + " --config " + shellQuote(configPath)

    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.title: i18n("AI Usage Monitor")
    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar ? fullRepresentation : compactRepresentation
    Layout.minimumWidth: Kirigami.Units.gridUnit * 12
    Layout.minimumHeight: Kirigami.Units.gridUnit * 5
    Layout.preferredWidth: Kirigami.Units.gridUnit * 17
    Layout.preferredHeight: Kirigami.Units.gridUnit * 13

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

    // Group flat items by their "group" field, preserving first-seen order.
    function groupsModel() {
        var order = []
        var map = ({})
        for (var i = 0; i < usageItems.length; i++) {
            var it = usageItems[i]
            var g = it.group || i18n("Usage")
            if (map[g] === undefined) {
                map[g] = []
                order.push(g)
            }
            map[g].push(it)
        }
        var out = []
        for (var j = 0; j < order.length; j++) {
            out.push({ "name": order[j], "items": map[order[j]] })
        }
        return out
    }

    // One {percent, color} chip per group, using the group's worst item.
    function compactSummary() {
        var groups = groupsModel()
        var out = []
        for (var i = 0; i < groups.length; i++) {
            var items = groups[i].items
            var worst = -1
            var worstItem = null
            for (var j = 0; j < items.length; j++) {
                var p = percentFor(items[j])
                if (p > worst) {
                    worst = p
                    worstItem = items[j]
                }
            }
            out.push({ "percent": Math.round(Math.max(0, worst)), "color": statusColor(worstItem) })
        }
        return out
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
        Layout.minimumWidth: compactRow.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.minimumHeight: Kirigami.Units.gridUnit * 2
        onClicked: root.expanded = !root.expanded

        RowLayout {
            id: compactRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.rightMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "utilities-system-monitor"
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
            }

            PlasmaComponents3.Label {
                visible: !root.loaded
                text: i18n("…")
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: root.loaded ? root.compactSummary() : []

                delegate: PlasmaComponents3.Label {
                    text: modelData.percent + "%"
                    color: modelData.color
                    font.bold: true
                    verticalAlignment: Text.AlignVCenter
                }
            }

            PlasmaComponents3.Label {
                visible: root.loaded && root.compactSummary().length === 0
                text: "--"
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    fullRepresentation: Item {
        implicitWidth: Kirigami.Units.gridUnit * 17
        implicitHeight: Kirigami.Units.gridUnit * 13

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            // Header
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "utilities-system-monitor"
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: Kirigami.Units.iconSizes.medium
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: i18n("AI Usage Monitor")
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize + 1
                        elide: Text.ElideRight
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: root.loaded
                        text: root.hasError && root.errorMessage
                            ? root.errorMessage
                            : i18n("Updated %1", root.updatedAt)
                        color: root.hasError ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.disabledTextColor
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                    }
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "view-refresh"
                    display: PlasmaComponents3.AbstractButton.IconOnly
                    text: i18n("Refresh")
                    PlasmaComponents3.ToolTip.text: text
                    PlasmaComponents3.ToolTip.visible: hovered
                    onClicked: root.refresh()
                }
            }

            Kirigami.Separator { Layout.fillWidth: true }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: !root.loaded
                text: i18n("Loading usage data…")
                color: Kirigami.Theme.disabledTextColor
            }

            // Grouped usage sections
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing
                visible: root.loaded && root.usageItems.length > 0

                Repeater {
                    model: root.groupsModel()

                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        required property var modelData

                        PlasmaComponents3.Label {
                            text: modelData.name
                            font.bold: true
                            font.capitalization: Font.AllUppercase
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: Kirigami.Theme.disabledTextColor
                            elide: Text.ElideRight
                        }

                        Repeater {
                            model: modelData.items

                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                required property var modelData
                                readonly property real pct: root.percentFor(modelData)
                                readonly property color accent: root.statusColor(modelData)

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing

                                    PlasmaComponents3.Label {
                                        Layout.fillWidth: true
                                        text: modelData.name || i18n("Usage")
                                        elide: Text.ElideRight
                                    }

                                    PlasmaComponents3.Label {
                                        text: Math.round(pct) + "%"
                                        font.bold: true
                                        color: accent
                                    }
                                }

                                // Custom rounded progress bar, colored by status
                                Rectangle {
                                    Layout.fillWidth: true
                                    height: Math.round(Kirigami.Units.gridUnit * 0.4)
                                    radius: height / 2
                                    color: Qt.rgba(Kirigami.Theme.textColor.r,
                                                   Kirigami.Theme.textColor.g,
                                                   Kirigami.Theme.textColor.b, 0.12)

                                    Rectangle {
                                        height: parent.height
                                        radius: parent.radius
                                        width: Math.max(parent.height, parent.width * Math.min(1, pct / 100))
                                        color: accent

                                        Behavior on width {
                                            NumberAnimation {
                                                duration: Kirigami.Units.longDuration
                                                easing.type: Easing.OutCubic
                                            }
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing

                                    PlasmaComponents3.Label {
                                        text: root.usageText(modelData)
                                        font: Kirigami.Theme.smallFont
                                        color: Kirigami.Theme.disabledTextColor
                                    }

                                    Item { Layout.fillWidth: true }

                                    PlasmaComponents3.Label {
                                        Layout.maximumWidth: parent.width * 0.6
                                        visible: Boolean(modelData.detail)
                                        text: modelData.detail || ""
                                        font: Kirigami.Theme.smallFont
                                        color: Kirigami.Theme.disabledTextColor
                                        horizontalAlignment: Text.AlignRight
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
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
                visible: root.hasError && Plasmoid.configuration.showDebugDetails && root.debugMessage
                text: root.debugMessage
                color: Kirigami.Theme.disabledTextColor
                font: Kirigami.Theme.smallFont
                wrapMode: Text.WordWrap
                maximumLineCount: 6
                elide: Text.ElideRight
            }

            Item { Layout.fillHeight: true }
        }
    }
}
