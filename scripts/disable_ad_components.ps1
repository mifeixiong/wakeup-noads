param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$androidNs = 'http://schemas.android.com/apk/res/android'

# Known ad-component candidates. Revalidate the namespace rule against each new
# Manifest before reuse and record any additions in that version's report.
$adComponentPattern = '^com\.(?:fastad|homework\.fastad|kwad|qq\.e|byazt|bytedance\.sdk\.openadsdk|bytedance\.msdk|bytedance\.android\.openliveplugin|byted\.live\.lite|baidu\.mobads|baidu\.oauth\.sdkbqt|component\.patchad)(?:\.|\$)'
$explicitAdComponents = @(
    'com.suda.yzune.wakeupschedule.aaa.resume.ResumeSplashActivity',
    'com.bun.miitmdid.utilsforrequestpermission.PermissionTransparentActivity'
)
$adOnlyPermissions = @(
    'android.permission.READ_PHONE_STATE',
    'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.ACCESS_FINE_LOCATION',
    'com.suda.yzune.wakeupschedule.openadsdk.permission.TT_PANGOLIN',
    'com.asus.msa.SupplementaryDID.ACCESS',
    'freemme.permission.msa',
    'freemme.permission.msa.SECURITY_ACCESS',
    'oplus.permission.settings.LAUNCH_FOR_EXPORT',
    'com.vivo.identifier.permission.OAID_STATE_DIALOG',
    'com.nemu.oaid.permission.read',
    'com.nemu.oaid.permission.write'
)

$resolvedManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path
$doc = New-Object System.Xml.XmlDocument
$doc.PreserveWhitespace = $true
$doc.Load($resolvedManifestPath)

$disabled = [System.Collections.Generic.List[string]]::new()
$components = $doc.SelectNodes('/manifest/application/activity | /manifest/application/activity-alias | /manifest/application/service | /manifest/application/receiver | /manifest/application/provider')
foreach ($component in $components) {
    $name = $component.GetAttribute('name', $androidNs)
    if ($name -match $adComponentPattern -or $explicitAdComponents -contains $name) {
        $enabled = $component.GetAttributeNode('enabled', $androidNs)
        if ($null -eq $enabled) {
            $enabled = $doc.CreateAttribute('android', 'enabled', $androidNs)
            [void]$component.Attributes.Append($enabled)
        }
        $enabled.Value = 'false'
        $disabled.Add("$($component.LocalName):$name")
    }
}

$removedPermissions = [System.Collections.Generic.List[string]]::new()
$permissionNodes = @($doc.SelectNodes('/manifest/uses-permission | /manifest/permission'))
foreach ($permissionNode in $permissionNodes) {
    $name = $permissionNode.GetAttribute('name', $androidNs)
    if ($adOnlyPermissions -contains $name) {
        [void]$permissionNode.ParentNode.RemoveChild($permissionNode)
        $removedPermissions.Add($name)
    }
}

$removedMetadata = [System.Collections.Generic.List[string]]::new()
$metadataNodes = @($doc.SelectNodes('/manifest/application/meta-data'))
foreach ($metadata in $metadataNodes) {
    $name = $metadata.GetAttribute('name', $androidNs)
    if ($name -eq 'com.huawei.hms.client.service.name:ads-identifier') {
        [void]$metadata.ParentNode.RemoveChild($metadata)
        $removedMetadata.Add($name)
    }
}

$doc.Save($resolvedManifestPath)

[PSCustomObject]@{
    DisabledComponentCount = $disabled.Count
    DisabledComponents = $disabled
    RemovedPermissionCount = $removedPermissions.Count
    RemovedPermissions = $removedPermissions
    RemovedMetadataCount = $removedMetadata.Count
    RemovedMetadata = $removedMetadata
} | ConvertTo-Json -Depth 4
