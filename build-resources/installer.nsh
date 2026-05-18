; 설치 후 시작 메뉴에 제거 바로가기 추가
!macro customInstall
  CreateDirectory "$SMPROGRAMS\주차 CX 모니터"
  CreateShortcut "$SMPROGRAMS\주차 CX 모니터\제거.lnk" \
    "$INSTDIR\Uninstall 주차 서비스 CX 모니터.exe" "" \
    "$INSTDIR\Uninstall 주차 서비스 CX 모니터.exe" 0
!macroend

!macro customUnInstall
  Delete "$SMPROGRAMS\주차 CX 모니터\제거.lnk"
!macroend
