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
        ]
      };
    }

    /* -----------------------------
       Connection
    ----------------------------- */

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
        } catch (error) {
          // Ignore errors while closing.
        }
      }

      this.socket = null;
      this.connected = false;
    }

    isConnected() {
      return (
        this.connected &&
        this.socket &&
        this.socket.readyState === WebSocket.OPEN
      );
    }

    /* -----------------------------
       Variables
    ----------------------------- */

    findGlobalVariable(name) {
      const variableName = Scratch.Cast.toString(name);
      const stage = runtime.getTargetForStage();

      if (!stage || !stage.variables) {
        return null;
      }

      for (const variable of Object.values(stage.variables)) {
        if (
          variable.name === variableName &&
          variable.type === ""
        ) {
          return variable;
        }
      }

      return null;
    }

    exposeVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);
      const variable = this.findGlobalVariable(name);

      if (!variable) {
        this.handleError(`Global variable "${name}" was not found`);
        return;
      }

      this.exposedVariables.add(name);

      if (this.isConnected()) {
        this.sendPacket({
          type: "expose_variable",
          name: name
        });
      }
    }

    hideVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);
      this.exposedVariables.delete(name);

      if (this.isConnected()) {
        this.sendPacket({
          type: "hide_variable",
          name: name
        });
      }
    }

    isVariableExposed(args) {
      const name = Scratch.Cast.toString(args.NAME);
      return this.exposedVariables.has(name);
    }

    setVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);
      const variable = this.findGlobalVariable(name);

      if (!variable) {
        this.handleError(`Global variable "${name}" was not found`);
        return;
      }

      variable.value = args.VALUE;
    }

    getVariable(args) {
      const name = Scratch.Cast.toString(args.NAME);
      const variable = this.findGlobalVariable(name);

      if (!variable) {
        return "";
      }

      return variable.value;
    }

    setVariableFromServer(name, value) {
      const variableName = Scratch.Cast.toString(name);

      if (!this.exposedVariables.has(variableName)) {
        this.sendPacket({
          type: "error",
          error: "variable_not_exposed",
          name: variableName
        });

        return false;
      }

      const variable = this.findGlobalVariable(variableName);

      if (!variable) {
        this.sendPacket({
          type: "error",
          error: "variable_not_found",
          name: variableName
        });

        return false;
      }

      variable.value = value;
      this.lastCommand = "set_variable";

      runtime.startHats("pixattach_whenVariableChanged");

      return true;
    }

    /* -----------------------------
       Sending and receiving
    ----------------------------- */

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
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
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

    handleMessage(rawMessage) {
      let packet;

      try {
        packet = JSON.parse(rawMessage);
      } catch (error) {
        this.lastValue = String(rawMessage);
        this.lastCommand = "value";

        runtime.startHats("pixattach_whenValueReceived");
        return;
      }

      if (!packet || typeof packet !== "object") {
        return;
      }

      this.lastCommand = packet.type || "unknown";

      switch (packet.type) {
        case "connected":
          break;

        case "value":
          this.lastValue =
            packet.value === undefined ? "" : packet.value;

          runtime.startHats("pixattach_whenValueReceived");
          break;

        case "set_variable": {
          const changed = this.setVariableFromServer(
            packet.name,
            packet.value
          );

          this.sendPacket({
            type: "set_variable_result",
            request_id: packet.request_id || "",
            name: packet.name,
            success: changed
          });

          break;
        }

        case "get_variable": {
          const name = Scratch.Cast.toString(packet.name);

          if (!this.exposedVariables.has(name)) {
            this.sendPacket({
              type: "variable_value",
              request_id: packet.request_id || "",
              name: name,
              success: false,
              error: "variable_not_exposed"
            });

            break;
          }

          const variable = this.findGlobalVariable(name);

          if (!variable) {
            this.sendPacket({
              type: "variable_value",
              request_id: packet.request_id || "",
              name: name,
              success: false,
              error: "variable_not_found"
            });

            break;
          }

          this.sendPacket({
            type: "variable_value",
            request_id: packet.request_id || "",
            name: name,
            value: variable.value,
            success: true
          });

          break;
        }

        case "ping":
          this.sendPacket({
            type: "pong",
            time: Date.now()
          });
          break;

        case "error":
          this.handleError(packet.message || packet.error || "Server error");
          break;

        default:
          this.lastValue = packet.value ?? rawMessage;
          runtime.startHats("pixattach_whenValueReceived");
          break;
      }
    }

    handleError(error) {
      this.lastError =
        error instanceof Error ? error.message : String(error);

      runtime.startHats("pixattach_whenError");
    }
  }

  Scratch.extensions.register(new PixAttach());
})(Scratch);
