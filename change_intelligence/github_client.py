from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Dict, List, Optional, Sequence

import jwt
import requests


COMMENT_MARKER = "<!-- change-intelligence-comment -->"


@dataclass
class GitHubConfig:
    app_id: Optional[str] = None
    private_key: Optional[str] = None
    token: Optional[str] = None
    api_url: str = "https://api.github.com"


class GitHubClient:
    def __init__(self, config: GitHubConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> Optional["GitHubClient"]:
        token = os.environ.get("GITHUB_TOKEN")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        private_key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
        if private_key is None and private_key_path:
            private_key = open(private_key_path, "r", encoding="utf8").read()
        app_id = os.environ.get("GITHUB_APP_ID")
        api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")

        if not token and not (app_id and private_key):
            return None

        return cls(
            GitHubConfig(
                app_id=app_id,
                private_key=private_key,
                token=token,
                api_url=api_url,
            )
        )

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        json_data: Optional[Dict[str, object]] = None,
        params: Optional[Dict[str, object]] = None,
    ) -> requests.Response:
        response = requests.request(
            method,
            f"{self.config.api_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "change-intelligence",
            },
            json=json_data,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response

    def _app_jwt(self) -> str:
        if not self.config.app_id or not self.config.private_key:
            raise ValueError("GitHub App credentials are not configured.")
        return jwt.encode(
            {
                "iat": int(__import__("time").time()) - 60,
                "exp": int(__import__("time").time()) + 540,
                "iss": self.config.app_id,
            },
            self.config.private_key,
            algorithm="RS256",
        )

    def _installation_token(self, installation_id: Optional[int]) -> str:
        if self.config.token:
            return self.config.token
        if installation_id is None:
            raise ValueError("Missing installation id for GitHub App authentication.")
        response = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),
        )
        return response.json()["token"]

    def pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        installation_id: Optional[int],
    ) -> List[Dict[str, object]]:
        token = self._installation_token(installation_id)
        page = 1
        files: List[Dict[str, object]] = []
        while True:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                token=token,
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    def issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: Optional[int],
    ) -> List[Dict[str, object]]:
        token = self._installation_token(installation_id)
        page = 1
        comments: List[Dict[str, object]] = []
        while True:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                token=token,
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            comments.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return comments

    def user_permission(
        self,
        owner: str,
        repo: str,
        username: str,
        installation_id: Optional[int],
    ) -> Optional[str]:
        token = self._installation_token(installation_id)
        try:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/collaborators/{username}/permission",
                token=token,
            )
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                return None
            raise
        payload = response.json()
        permission = payload.get("permission")
        return permission if isinstance(permission, str) else None

    def repo_docs(
        self,
        owner: str,
        repo: str,
        docs_path: str,
        ref: Optional[str],
        installation_id: Optional[int],
    ) -> List[Dict[str, str]]:
        token = self._installation_token(installation_id)
        docs: List[Dict[str, str]] = []
        stack: List[str] = [docs_path.strip("/")]

        def request_contents(path: str, path_ref: Optional[str]):
            return self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}",
                token=token,
                params={"ref": path_ref} if path_ref else None,
            )

        while stack:
            current = stack.pop()
            try:
                response = request_contents(current, ref)
            except requests.HTTPError as error:
                if ref and error.response is not None and error.response.status_code == 404:
                    response = request_contents(current, None)
                else:
                    raise
            payload = response.json()
            if isinstance(payload, dict) and payload.get("type") == "file":
                payload = [payload]

            for entry in payload:
                if entry["type"] == "dir":
                    stack.append(entry["path"])
                    continue
                if entry["type"] != "file":
                    continue
                if not entry["name"].lower().endswith((".md", ".mdx", ".txt")):
                    continue
                try:
                    file_response = request_contents(entry["path"], ref)
                except requests.HTTPError as error:
                    if ref and error.response is not None and error.response.status_code == 404:
                        file_response = request_contents(entry["path"], None)
                    else:
                        raise
                file_payload = file_response.json()
                content = __import__("base64").b64decode(file_payload["content"]).decode("utf8")
                docs.append(
                    {
                        "path": entry["path"],
                        "relative_path": entry["path"][len(docs_path.strip('/') + '/'):].lstrip("/"),
                        "content": content,
                    }
                )
        return docs

    def pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "closed",
        sort: str = "updated",
        direction: str = "desc",
        per_page: int = 30,
    ) -> List[Dict[str, object]]:
        token = self._installation_token(None)
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            token=token,
            params={
                "state": state,
                "sort": sort,
                "direction": direction,
                "per_page": per_page,
            },
        )
        return response.json()

    def commit_files(
        self,
        owner: str,
        repo: str,
        ref: str,
        installation_id: Optional[int],
    ) -> List[Dict[str, object]]:
        token = self._installation_token(installation_id)
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{ref}",
            token=token,
        )
        payload = response.json()
        files = payload.get("files") or []
        return [item for item in files if isinstance(item, dict)]

    def upsert_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: Optional[int],
        body: str,
    ) -> Dict[str, object]:
        token = self._installation_token(installation_id)
        comments = self.issue_comments(owner, repo, issue_number, installation_id)
        marked = next((item for item in comments if COMMENT_MARKER in item.get("body", "")), None)
        comment_body = f"{COMMENT_MARKER}\n{body}"

        if marked:
            update = self._request(
                "PATCH",
                f"/repos/{owner}/{repo}/issues/comments/{marked['id']}",
                token=token,
                json_data={"body": comment_body},
            )
            return update.json()

        created = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            token=token,
            json_data={"body": comment_body},
        )
        return created.json()

    def clear_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: Optional[int],
    ) -> Optional[Dict[str, object]]:
        token = self._installation_token(installation_id)
        comments = self.issue_comments(owner, repo, issue_number, installation_id)
        marked = next((item for item in comments if COMMENT_MARKER in item.get("body", "")), None)
        if not marked:
            return None
        self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/issues/comments/{marked['id']}",
            token=token,
        )
        return {"id": marked["id"], "deleted": True, "html_url": marked.get("html_url")}


def build_patch_from_files(files: Sequence[Dict[str, object]]) -> str:
    chunks: List[str] = []
    for item in files:
        patch = item.get("patch")
        filename = item.get("filename")
        if not patch or not filename:
            continue
        chunks.extend(
            [
                f"diff --git a/{filename} b/{filename}",
                f"--- a/{filename}",
                f"+++ b/{filename}",
                patch.rstrip("\n"),
            ]
        )
    return "\n".join(chunks) + ("\n" if chunks else "")
