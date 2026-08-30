import time

import pixattach


project = pixattach.connect(
    project_id="echo-os",
    server="wss://YOUR-RENDER-SERVICE.onrender.com/ws",
    token="YOUR_PIXATTACH_TOKEN",
)


@project.on_value
def receive(value):
    print("Gandi sent:", value)


print("ServerStatus:", project.get_var("ServerStatus"))
project.set_var("ServerStatus", "Online")
project.send("Hello from Python!")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    project.close()

