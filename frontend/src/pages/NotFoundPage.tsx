import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div style={{ padding: "4rem", textAlign: "center" }}>
      <h1>404</h1>
      <p>页面不存在</p>
      <Link to="/">返回首页</Link>
    </div>
  );
}
