<#
.SYNOPSIS
为已加入 Swarm 的三个管理节点分配服务角色标签。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateCount(3, 3)]
    [string[]]$ManagerNodes
)

$ErrorActionPreference = 'Stop'

$managerCount = docker node ls --filter role=manager --format '{{.Hostname}}' 2>$null
if (-not $managerCount) {
    throw 'Run docker swarm init on the first manager and join the other two managers before applying labels.'
}

foreach ($node in $ManagerNodes) {
    $match = docker node inspect $node --format '{{.Description.Hostname}}' 2>$null
    if (-not $match) { throw "Swarm manager node not found: $node" }
}

docker node update --label-add edu.role.edge=true --label-add edu.role.app=true $ManagerNodes[0]
docker node update --label-add edu.role.worker=true --label-add edu.role.runtime=true $ManagerNodes[1]
docker node update --label-add edu.role.data=true --label-add edu.role.app=true $ManagerNodes[2]

Write-Output 'Swarm labels applied. Create versioned external configs and the required django_secret_key, identity_hmac_key, course_invitation_hmac_key, mysql_app_password, mongodb_uri, minio_app_access_key, minio_app_secret_key, swarm_docker_ca, swarm_docker_cert, swarm_docker_key, tls_certificate, and tls_private_key secrets before deploying the stack.'
