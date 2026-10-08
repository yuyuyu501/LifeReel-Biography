export function newRequestId() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const random = Math.floor(Math.random() * 16);
    return (c === "x" ? random : (random & 3) | 8).toString(16);
  });
}
