import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
const routes = {
  "/": ["frontend/demo.html", "text/html; charset=utf-8"],
  "/panel.js": ["custom_components/ha_tgen/frontend/panel.js", "text/javascript"],
  "/demo.mp4": [".preview/demo.mp4", "video/mp4"],
};
createServer(async (request, response) => {
  const path = new URL(request.url, "http://localhost").pathname;
  if (!routes[path]) { response.writeHead(404).end(); return; }
  try {
    const [filename, type] = routes[path];
    const body = await readFile(filename);
    const range = request.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
    if (range) {
      const start = Number(range[1]), end = Math.min(Number(range[2]) || body.length - 1, body.length - 1);
      response.writeHead(206, { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${body.length}`, "Content-Length": end - start + 1 }).end(body.subarray(start, end + 1));
    } else response.writeHead(200, { "Content-Type": type, "Accept-Ranges": "bytes" }).end(body);
  } catch { response.writeHead(404).end(); }
}).listen(8124, "127.0.0.1", () => console.log("Panel preview: http://127.0.0.1:8124 (demo data)"));
