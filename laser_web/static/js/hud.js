// Text over the 3D scene (plain HTML, see index.html): player panels, the
// round timer, status messages and the big centre messages.

import { COUNTDOWN, OVER, PLAYING, WAITING } from "./duel.js";
import { PLAYER_COLORS } from "./scene.js";

export class Hud {
  constructor(mode) {
    this.mode = mode;
    this.el = (id) => document.getElementById(id);
    this.shown = new Map();         // element id -> text, to touch the DOM only on change
  }

  set(id, text) {
    if (this.shown.get(id) === text) return;
    this.shown.set(id, text);
    this.el(id).textContent = text;
  }

  update(duel, now, status) {
    for (const pid of [1, 2]) this.playerPanel(duel, pid, now);

    this.set("timer", duel.state === PLAYING ? `${duel.elapsed(now).toFixed(1)} s    wave ${duel.spawner.waves}` : "");
    this.set("status", status ?? "");

    let title = "";
    let lines = ["", ""];
    let titleColor = "var(--laser)";

    if (duel.state === WAITING) {
      const present = duel.present();
      if (present.length === 2) {
        lines = ["Get ready...", ""];
      } else {
        title = "LASER DUEL";
        lines = [
          "Player 1: left lane    Player 2: right lane",
          present.length ? "Press Enter to play solo" : "Jump, duck and step aside. First to touch a laser loses!",
        ];
      }
    } else if (duel.state === COUNTDOWN) {
      title = String(Math.max(1, Math.ceil(duel.countdownEnd - now)));
      lines = ["Stand tall, arms down: measuring you", ""];
    } else if (duel.state === OVER) {
      [title, lines, titleColor] = this.result(duel, now);
    }

    this.set("title", title);
    this.el("title").style.color = titleColor;
    this.set("line1", lines[0]);
    this.set("line2", lines[1]);
    this.set("help", this.mode === "keyboard" && duel.state === WAITING
      ? "Keyboard mode: A D W S / arrow keys move, jump, duck. 1 / 2: step in or out of view."
      : "");
  }

  playerPanel(duel, pid, now) {
    const player = duel.players.get(pid);
    const inView = duel.body(pid) !== null;
    const panel = this.el(`p${pid}`);

    let line;
    let color = `rgb(${PLAYER_COLORS[pid].join(",")})`;
    if (player && player.out) {
      line = "OUT";
      color = "#5a5a64";
    } else if (player) {
      line = `${player.lives} ${player.lives === 1 ? "life" : "lives"}`;
    } else if (inView) {
      line = "ready";
    } else {
      line = "not in view";
      color = "#464650";
    }
    panel.style.background = color;
    this.set(`p${pid}-label`, `P${pid}  ${line}`);

    const info = player && (duel.state === PLAYING || duel.state === OVER)
      ? `${player.height.toFixed(2)} m   ${duel.survived(player, now).toFixed(1)} s`
      : "";
    this.set(`p${pid}-info`, info);
  }

  result(duel, now) {
    const players = [...duel.players.values()];
    if (players.length === 1) {
      const [player] = players;
      return [`${duel.survived(player, now).toFixed(1)} seconds!`, [`Player ${player.pid} ${player.outReason}`, "Enter: play again"], "var(--laser)"];
    }
    if (duel.winner === null) {
      return ["Draw!", ["Both out at the same time", "Enter: play again"], "var(--laser)"];
    }
    const loser = players.find((player) => player.pid !== duel.winner);
    const color = `rgb(${PLAYER_COLORS[duel.winner].join(",")})`;
    return [`Player ${duel.winner} wins!`, [`Player ${loser.pid} ${loser.outReason}`, "Enter: play again"], color];
  }
}
