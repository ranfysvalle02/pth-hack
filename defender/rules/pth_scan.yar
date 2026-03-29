rule Malicious_PTH_File {
    meta:
        description = "Detects .pth files containing executable import + exec patterns"
        severity = "critical"
        mitre_technique = "T1546"
        mitre_name = "Event Triggered Execution"

    strings:
        $import = "import" ascii
        $exec = "exec(" ascii
        $urlopen = "urlopen" ascii
        $urllib = "urllib" ascii

    condition:
        $import and ($exec or ($urlopen and $urllib))
}

rule PTH_C2_Fetch {
    meta:
        description = "Detects .pth file fetching remote payload via HTTP"
        severity = "critical"
        mitre_technique = "T1105"
        mitre_name = "Ingress Tool Transfer"

    strings:
        $pth_import = /^import\s/ ascii
        $http = "http://" ascii
        $exec = "exec(" ascii

    condition:
        all of them
}
