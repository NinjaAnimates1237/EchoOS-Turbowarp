(function (Scratch) {
  "use strict";

  if (!Scratch.extensions.unsandboxed) {
    throw new Error("PixAttach must run unsandboxed.");
  }

  const runtime = Scratch.vm.runtime;

  class PixAttach {
    constructor() {
      this.socket = null;
      this.connected = false;
      this.projectID = "";
      this.token = "";
      this.lastValue = "";
      this.lastCommand = "";
      this.lastError = "";
      this.exposedVariables = new Set();

      this.pixVariables = new Map();
      this.lastPixVariableName = "";
      this.lastPixVariableValue = "";
    }

    getInfo() {
      return {
        id: "pixattach",
        name: "PixAttach",
        color1: "#7066FF",
        color2: "#564BCB",
        color3: "#4037A6",

        blocks: [
          {
            opcode: "connect",
            blockType: Scratch.BlockType.COMMAND,
            text: "connect to PixAttach [URL] project [PROJECT] token [TOKEN]",
            arguments: {
              URL: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "ws://localhost:8000/ws"
              },
              PROJECT: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "my-project"
              },
              TOKEN: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "development-token"
              }
            }
          },

          {
            opcode: "disconnect",
            blockType: Scratch.BlockType.COMMAND,
            text: "disconnect from PixAttach"
          },

          {
            opcode: "isConnected",
            blockType: Scratch.BlockType.BOOLEAN,
            text: "connected to PixAttach?"
          },

          "---",

          {
            opcode: "exposeVariable",
            blockType: Scratch.BlockType.COMMAND,
            text: "expose variable [NAME]",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Score"
              }
            }
          },

          {
            opcode: "hideVariable",
            blockType: Scratch.BlockType.COMMAND,
            text: "hide variable [NAME]",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Score"
              }
            }
          },

          {
            opcode: "setVariable",
            blockType: Scratch.BlockType.COMMAND,
            text: "set variable [NAME] to [VALUE]",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Score"
              },
              VALUE: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "100"
              }
            }
          },

          {
            opcode: "getVariable",
            blockType: Scratch.BlockType.REPORTER,
            text: "get variable [NAME]",
            allowDropAnywhere: true,
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Score"
              }
            }
          },

          {
            opcode: "isVariableExposed",
            blockType: Scratch.BlockType.BOOLEAN,
            text: "variable [NAME] exposed?",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Score"
              }
            }
          },

          "---",

          {
            blockType: Scratch.BlockType.BUTTON,
            text: "Make A Pix Var",
            func: "createPixVariable"
          },

          {
            opcode: "setPixVariable",
            blockType: Scratch.BlockType.COMMAND,
            text: "set Pix Var [NAME] to [VALUE]",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                menu: "pixVariableMenu"
              },
              VALUE: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Hello!"
              }
            }
          },

          {
            opcode: "getPixVariable",
            blockType: Scratch.BlockType.REPORTER,
            text: "Pix Var [NAME]",
            allowDropAnywhere: true,
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                menu: "pixVariableMenu"
              }
            }
          },

          {
            opcode: "deletePixVariable",
            blockType: Scratch.BlockType.COMMAND,
            text: "delete Pix Var [NAME]",
            arguments: {
              NAME: {
                type: Scratch.ArgumentType.STRING,
                menu: "pixVariableMenu"
              }
            }
          },

          {
            opcode: "lastChangedPixVariable",
            blockType: Scratch.BlockType.REPORTER,
            text: "changed Pix Var",
            allowDropAnywhere: true
          },

          {
            opcode: "lastChangedPixValue",
            blockType: Scratch.BlockType.REPORTER,
            text: "changed Pix Var value",
            allowDropAnywhere: true
          },

          {
            opcode: "whenPixVariableChanged",
            blockType: Scratch.BlockType.HAT,
            text: "when a Pix Var changes",
            isEdgeActivated: false
          },

          "---",

          {
            opcode: "sendValue",
            blockType: Scratch.BlockType.COMMAND,
            text: "send [VALUE]",
            arguments: {
              VALUE: {
                type: Scratch.ArgumentType.STRING,
                defaultValue: "Hello!"
              }
            }
          },

          {
            opcode: "receivedValue",
            blockType: Scratch.BlockType.REPORTER,
            text: "received value",
            allowDropAnywhere: true
          },

          {
            opcode: "receivedCommand",
            blockType: Scratch.BlockType.REPORTER,
            text: "received command",
            allowDropAnywhere: true
          },

          {
            opcode: "connectionError",
            blockType: Scratch.BlockType.REPORTER,
            text: "connection error",
            allowDropAnywhere: true
          },

          "---",

          {
            opcode: "whenConnected",
            blockType: Scratch.BlockType.HAT,
            text: "when PixAttach connects",
            isEdgeActivated: false
          },

          {
            opcode: "whenDisconnected",
            blockType: Scratch.BlockType.HAT,
            text: "when PixAttach disconnects",
            isEdgeActivated: false
          },

          {
            opcode: "whenValueReceived",
            blockType: Scratch.BlockType.HAT,
            text: "when PixAttach receives a value",
            isEdgeActivated: false
          },

          {
            opcode: "whenVariableChanged",
            blockType: Scratch.BlockType.HAT,
            text: "when PixAttach changes a variable",
            isEdgeActivated: false
          },

          {
            opcode: "whenError",
            blockType: Scratch.BlockType.HAT,
            text: "when PixAttach error occurs",
            isEdgeActivated: false
          }
        ],

        menus: {
          pixVariableMenu: {
            acceptReporters: true,
            items: "getPixVariableMenu"
          }
        }
      };
    }

    refreshBlocks() {
      try {
        Scratch.vm.extensionManager.refreshBlocks();
      } catch (_) {}
    }

    getPixVariableMenu() {
      const names = Array.from(this.pixVariables.keys()).sort();
      return names.length ? names : ["message"];
    }

    createPixVariable() {
      const answer = window.prompt(
        "Make A Pix Var\n\nVariable name:",
        "message"
      );

      if (answer === null) return;

      const name = String(answer).trim();

      if (!name) {
        this.handleError("Pix Var name cannot be empty");
        return;
      }

      if (name.length > 64) {
        this.handleError("Pix Var names can be at most 64 characters");
        return;
      }

      if (!this.pixVariables.has(name)) {
        this.pixVariables.set(name, "");
      }

      this.refreshBlocks();

      if (this.isConnected()) {
        this.sendPacket({
          type: "set_pix_variable",
          name,
          value: this.pixVariables.get(name)
        });
      }
    }

    setPixVariable(args) {
      const name = Scratch.Cast.toString(args.NAME).trim();

      if (!name) {
        this.handleError("Pix Var name cannot be empty");
        return;
      }

      const value = args.VALUE;

      this.updatePixVariable(name, value, false);

      if (!this.isConnected()) {
        this.handleError("PixAttach is not connected");
        return;
      }

      this.sendPacket({
        type: "set_pix_variable",
        name,
        value
      });
    }

    getPixVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);

      if (this.pixVariables.has(name)) {
        return this.pixVariables.get(name);
      }

      return "";
    }

    deletePixVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);

      this.pixVariables.delete(name);
      this.refreshBlocks();

      if (!this.isConnected()) {
        this.handleError("PixAttach is not connected");
        return;
      }

      this.sendPacket({
        type: "delete_pix_variable",
        name
      });
    }

    lastChangedPixVariable() {
      return this.lastPixVariableName;
    }

    lastChangedPixValue() {
      return this.lastPixVariableValue;
    }

    updatePixVariable(name, value, fireHat = true) {
      name = Scratch.Cast.toString(name);

      const isNew = !this.pixVariables.has(name);

      this.pixVariables.set(name, value ?? "");
      this.lastPixVariableName = name;
      this.lastPixVariableValue = value ?? "";

      if (isNew) {
        this.refreshBlocks();
      }

      if (fireHat) {
        runtime.startHats("pixattach_whenPixVariableChanged");
      }
    }

    connect(args) {
      const url = Scratch.Cast.toString(args.URL);

      this.projectID = Scratch.Cast.toString(args.PROJECT);
      this.token = Scratch.Cast.toString(args.TOKEN);

      this.disconnect();
      this.lastError = "";

      try {
        this.socket = new WebSocket(url);
      } catch (error) {
        this.handleError(error);
        return;
      }

      this.socket.addEventListener("open", () => {
        this.connected = true;

        this.sendPacket({
          type: "connect",
          client_type: "project",
          project_id: this.projectID,
          token: this.token,
          exposed_variables: Array.from(this.exposedVariables)
        });

        runtime.startHats("pixattach_whenConnected");
      });

      this.socket.addEventListener("message", event => {
        this.handleMessage(event.data);
      });

      this.socket.addEventListener("close", () => {
        const wasConnected = this.connected;

        this.connected = false;
        this.socket = null;

        if (wasConnected) {
          runtime.startHats("pixattach_whenDisconnected");
        }
      });

      this.socket.addEventListener("error", () => {
        this.handleError("WebSocket connection error");
      });
    }

    disconnect() {
      if (this.socket) {
        try {
          this.socket.close();
        } catch (_) {}
      }

      this.socket = null;
      this.connected = false;
    }

    isConnected() {
      return Boolean(
        this.connected &&
        this.socket &&
        this.socket.readyState === WebSocket.OPEN
      );
    }

    findGlobalVariable(name) {
      const stage = runtime.getTargetForStage();

      if (!stage || !stage.variables) {
        return null;
      }

      const wanted = Scratch.Cast.toString(name);

      return (
        Object.values(stage.variables).find(variable => {
          return variable.name === wanted && variable.type === "";
        }) || null
      );
    }

    exposeVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);

      if (!this.findGlobalVariable(name)) {
        this.handleError(`Global variable "${name}" was not found`);
        return;
      }

      this.exposedVariables.add(name);

      if (this.isConnected()) {
        this.sendPacket({
          type: "expose_variable",
          name
        });
      }
    }

    hideVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);

      this.exposedVariables.delete(name);

      if (this.isConnected()) {
        this.sendPacket({
          type: "hide_variable",
          name
        });
      }
    }

    isVariableExposed(args) {
      return this.exposedVariables.has(
        Scratch.Cast.toString(args.NAME)
      );
    }

    setVariable(args) {
      const variable = this.findGlobalVariable(args.NAME);

      if (!variable) {
        this.handleError(
          `Global variable "${Scratch.Cast.toString(args.NAME)}" was not found`
        );
        return;
      }

      variable.value = args.VALUE;
    }

    getVariable(args) {
      const variable = this.findGlobalVariable(args.NAME);
      return variable ? variable.value : "";
    }

    sendValue(args) {
      if (!this.isConnected()) {
        this.handleError("PixAttach is not connected");
        return;
      }

      this.sendPacket({
        type: "value",
        value: args.VALUE
      });
    }

    receivedValue() {
      return this.lastValue;
    }

    receivedCommand() {
      return this.lastCommand;
    }

    connectionError() {
      return this.lastError;
    }

    sendPacket(packet) {
      if (
        !this.socket ||
        this.socket.readyState !== WebSocket.OPEN
      ) {
        return false;
      }

      try {
        this.socket.send(JSON.stringify(packet));
        return true;
      } catch (error) {
        this.handleError(error);
        return false;
      }
    }

    setVariableFromServer(name, value) {
      name = Scratch.Cast.toString(name);

      if (!this.exposedVariables.has(name)) {
        return false;
      }

      const variable = this.findGlobalVariable(name);

      if (!variable) {
        return false;
      }

      variable.value = value;
      this.lastCommand = "set_variable";

      runtime.startHats("pixattach_whenVariableChanged");

      return true;
    }

    handleMessage(raw) {
      let packet;

      try {
        packet = JSON.parse(raw);
      } catch (_) {
        this.lastValue = String(raw);
        this.lastCommand = "value";

        runtime.startHats("pixattach_whenValueReceived");
        return;
      }

      if (!packet || typeof packet !== "object") {
        return;
      }

      this.lastCommand = packet.type || "unknown";

      if (packet.type === "value") {
        this.lastValue = packet.value ?? "";

        runtime.startHats("pixattach_whenValueReceived");
      }

      else if (packet.type === "set_variable") {
        const success = this.setVariableFromServer(
          packet.name,
          packet.value
        );

        this.sendPacket({
          type: "set_variable_result",
          request_id: packet.request_id || "",
          name: packet.name,
          success
        });
      }

      else if (packet.type === "get_variable") {
        const name = Scratch.Cast.toString(packet.name);

        const variable =
          this.exposedVariables.has(name)
            ? this.findGlobalVariable(name)
            : null;

        this.sendPacket({
          type: "variable_value",
          request_id: packet.request_id || "",
          name,
          value: variable ? variable.value : "",
          success: Boolean(variable),
          error: variable
            ? ""
            : "variable_not_exposed_or_not_found"
        });
      }

      else if (packet.type === "pix_variables") {
        const variables =
          packet.variables &&
          typeof packet.variables === "object"
            ? packet.variables
            : {};

        this.pixVariables = new Map(
          Object.entries(variables)
        );

        this.refreshBlocks();
      }

      else if (packet.type === "pix_variable_changed") {
        this.updatePixVariable(
          packet.name,
          packet.value,
          true
        );
      }

      else if (packet.type === "pix_variable_deleted") {
        const name = Scratch.Cast.toString(packet.name);

        this.pixVariables.delete(name);
        this.lastPixVariableName = name;
        this.lastPixVariableValue = "";

        this.refreshBlocks();

        runtime.startHats(
          "pixattach_whenPixVariableChanged"
        );
      }

      else if (packet.type === "ping") {
        this.sendPacket({
          type: "pong",
          time: Date.now()
        });
      }

      else if (packet.type === "error") {
        this.handleError(
          packet.message ||
          packet.error ||
          "Server error"
        );
      }
    }

    handleError(error) {
      this.lastError =
        error instanceof Error
          ? error.message
          : String(error);

      runtime.startHats("pixattach_whenError");
    }
  }

  Scratch.extensions.register(new PixAttach());
})(Scratch);
