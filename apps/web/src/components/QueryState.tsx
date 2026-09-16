import { Button } from "./ui/button";
import { AlertCircle, RefreshCw } from "lucide-react";
import { errorMessage } from "../api/errors";
import type { QueryLike } from "../queryHelpers";
import { Skeleton } from "./ui/skeleton";

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
        <Button
          variant="outline"
          size="sm"
          className="button secondary small"
          onClick={() => failed.refetch()}
        >
          <RefreshCw size={15} /> 重试
        </Button>
      </div>
    );
  }
  if (queries.some((query) => query.isPending)) {
    return (
      <div className="query-state loading" role="status" aria-live="polite">
        <span>{loadingText}</span>
        <div className="query-skeleton" aria-hidden="true">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
    );
  }
  return null;
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="notice error" role="alert">
      {errorMessage(error)}
    </div>
  );
}
