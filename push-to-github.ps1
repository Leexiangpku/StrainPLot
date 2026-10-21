# 把本地仓库推送到 GitHub（在能正常访问 github.com 的机器上运行）
#
# 用法：
#   .\push-to-github.ps1 -Repo https://github.com/<你的用户名>/StrainPlot.git
#   .\push-to-github.ps1 -Repo https://github.com/<你的用户名>/StrainPlot.git -Token ghp_xxx
#
# 说明：
#   - 仓库已在本地完成提交（main 分支）并打了版本 tag（如 v0.20）；
#   - 本脚本会推送分支 + 全部 tag；
#   - 不传 -Token 时交给 Git 凭据管理器提示登录（推荐，token 不会留在历史里）；
#   - 目标仓库需先在网页端新建（空仓库，不要勾选 README/.gitignore）；
#   - 完全没网时，也可用 dist\StrainPlot-0.20-repo.bundle 在别的机器上还原：
#       git clone StrainPlot-0.20-repo.bundle StrainPlot
param(
    [Parameter(Mandatory = $true)]
    [string]$Repo,

    [string]$Branch = "main",

    [string]$Token
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path ".git")) {
    throw "当前目录不是 git 仓库：$((Get-Location).Path)"
}

$remote = "origin"
$url = $Repo
if ($Token) {
    # https://<token>@github.com/user/repo.git
    $url = $Repo -replace "^https://", "https://$Token@"
}

if (git remote | Select-String -Quiet "^$remote$") {
    Write-Host "更新 remote $remote -> $Repo"
    git remote set-url $remote $url
} else {
    Write-Host "添加 remote $remote -> $Repo"
    git remote add $remote $url
}

Write-Host "推送到 $Repo ($Branch) ..."
git push -u $remote $Branch
git push $remote --tags

if ($Token) {
    # 避免 token 明文留在 .git/config 里
    git remote set-url $remote $Repo
    Write-Host "已把 remote URL 还原为不含 token 的形式。"
}

Write-Host "完成：$Repo"
