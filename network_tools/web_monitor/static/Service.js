/*jshint esversion: 6 */
"use strict";

class Service {
    constructor(serviceName, elm) {
        /*
        a class
         */
        this.serviceName = serviceName;
        this.elm = elm;
    }

    $(selector) {
        return this.elm.querySelector(selector);
    }

    //======================================================//
    // Start/stop/restart
    //======================================================//

    stop() {
        new AjaxRequest("stop_service").send();
    }
    start() {
        new AjaxRequest("start_service").send();
    }
    restart() {
        new AjaxRequest("restart_service").send();
    }

    //======================================================//
    // Base update methods
    //======================================================//

    update(o) {
        this.updateStatusTable(o["table_html"]);
        this.updateGraphs(o["graphs"]);

        if (o["console_text"]) {
            this.writeConsoleText(o["console_text"]);
        }
    }

    updateStatusTable(tableHTML) {
        this.$(
            ".status_table_cont_div"
        ).innerHTML = tableHTML;
    }

    //======================================================//
    // Graphs
    //======================================================//

    updateGraphs(o) {
        if (!this.graphsInit) {
            this.ramGraph = new LineChart(
                this.$("ram"), o["labels"], o["ram"]
            );
            this.cpuGraph = new LineChart(
                this.$("cpu"), o["labels"], o["cpu"]
            );
            this.ioGraph = new LineChart(
                this.$("io"), o["labels"], o["io"]
            );
            this.graphsInit = true;
        }
        else {
            this.ramGraph.update(o["labels"], o["ram"]);
            this.cpuGraph.update(o["labels"], o["cpu"]);
            this.ioGraph.update(o["labels"], o["io"]);
        }
    }

    //======================================================//
    // Console Text
    //======================================================//

    writeConsoleText(text) {
        this.consoleDiv.appendChild(
            // TODO: Check whitespace is preserved here!! =====================================================
            document.createTextNode(text)
        );
    }
}