const form = document.getElementById("login-form");
const error = document.getElementById("login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const data = new FormData(form);
  const body = new URLSearchParams();
  body.set("version", "1.0");
  body.set("username", data.get("username"));
  body.set("password", data.get("password"));
  const response = await fetch("/api/v2/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    error.textContent = "用户名或密码不正确";
    return;
  }
  window.location.assign("/");
});
