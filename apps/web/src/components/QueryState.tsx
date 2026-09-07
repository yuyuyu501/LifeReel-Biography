import { AlertCircle, RefreshCw } from "lucide-react";
import { errorMessage } from "../api/errors";
import type { QueryLike } from "../queryHelpers";

export function QueryState({
  queries,
  loadingText = "正在加载……",
}: {
  queries: QueryLike[];
  loadingText?: string;
}) {
  const failed = queries.find((query) => query.isError);
  if (failed) {
    return (
      <div className="query-state error" role="alert">
        <AlertCircle size={22} />
        <div>
          <strong>内容加载失败</strong>
          <p>{errorMessage(failed.error)}</p>
        </div>
        <button className="button secondary small" onClick={() => failed.refetch()}>
          <RefreshCw size={15} /> 重试
        </button>
      </div>
    );
  }
  if (queries.some((query) => query.isPending)) {
    return <div className="query-state loading">{loadingText}</div>;
  }
  return null;
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="notice error" role="alert">{errorMessage(error)}</div>;
}
