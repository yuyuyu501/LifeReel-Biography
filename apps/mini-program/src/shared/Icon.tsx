import { Image } from "@tarojs/components";

const assets = {
  help: [
    require("../assets/help-muted.png"),
    require("../assets/help-green.png"),
    require("../assets/help-white.png"),
  ],
  users: [
    require("../assets/users-muted.png"),
    require("../assets/users-green.png"),
    require("../assets/users-white.png"),
  ],
  mic: [
    require("../assets/mic-muted.png"),
    require("../assets/mic-green.png"),
    require("../assets/mic-white.png"),
  ],
  book: [
    require("../assets/book-muted.png"),
    require("../assets/book-green.png"),
    require("../assets/book-white.png"),
  ],
  film: [
    require("../assets/film-muted.png"),
    require("../assets/film-green.png"),
    require("../assets/film-white.png"),
  ],
  archive: [
    require("../assets/archive-muted.png"),
    require("../assets/archive-green.png"),
    require("../assets/archive-white.png"),
  ],
  profile: [
    require("../assets/profile-muted.png"),
    require("../assets/profile-green.png"),
    require("../assets/profile-white.png"),
  ],
  plus: [
    require("../assets/plus-muted.png"),
    require("../assets/plus-green.png"),
    require("../assets/plus-white.png"),
  ],
  arrow: [
    require("../assets/arrow-muted.png"),
    require("../assets/arrow-green.png"),
    require("../assets/arrow-white.png"),
  ],
  back: [
    require("../assets/back-muted.png"),
    require("../assets/back-green.png"),
    require("../assets/back-white.png"),
  ],
  down: [
    require("../assets/down-muted.png"),
    require("../assets/down-green.png"),
    require("../assets/down-white.png"),
  ],
  refresh: [
    require("../assets/refresh-muted.png"),
    require("../assets/refresh-green.png"),
    require("../assets/refresh-white.png"),
  ],
  send: [
    require("../assets/send-muted.png"),
    require("../assets/send-green.png"),
    require("../assets/send-white.png"),
  ],
  lock: [
    require("../assets/lock-muted.png"),
    require("../assets/lock-green.png"),
    require("../assets/lock-white.png"),
  ],
  edit: [
    require("../assets/edit-muted.png"),
    require("../assets/edit-green.png"),
    require("../assets/edit-white.png"),
  ],
  check: [
    require("../assets/check-muted.png"),
    require("../assets/check-green.png"),
    require("../assets/check-white.png"),
  ],
  stop: [
    require("../assets/stop-muted.png"),
    require("../assets/stop-green.png"),
    require("../assets/stop-white.png"),
  ],
  logout: [
    require("../assets/logout-muted.png"),
    require("../assets/logout-green.png"),
    require("../assets/logout-white.png"),
  ],
};

export type IconName = keyof typeof assets;

export function Icon({
  name,
  tone = "green",
}: {
  name: IconName;
  tone?: "muted" | "green" | "white";
}) {
  return (
    <Image
      className="ui-icon"
      src={assets[name][["muted", "green", "white"].indexOf(tone)]}
      mode="aspectFit"
    />
  );
}
