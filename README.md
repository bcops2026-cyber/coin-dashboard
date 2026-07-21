# BITCLUB Research · 빗썸 단독 상장 코인 대시보드

빗썸에만 상장되고 업비트엔 없는 코인들의 해외 거래소 상장 현황을 실시간으로 추적하는 대시보드입니다.

## 사이트 접속

[bitclub-research.github.io/coin-dashboard](https://bitclub-research.github.io/coin-dashboard) *(배포 후 활성화)*

## 자동 갱신

- GitHub Actions로 **매시간 자동 실행**
- 거래소 API에서 데이터 수집 → 사이트 갱신
- 변동사항 발생 시 로그 자동 기록

## 데이터 출처

- [Bithumb Public API](https://apidocs.bithumb.com/)
- [Upbit Open API](https://docs.upbit.com/)
- [Binance API](https://binance-docs.github.io/apidocs/)
- [Coinbase Exchange API](https://docs.cloud.coinbase.com/exchange/)
- [Kraken REST API](https://docs.kraken.com/rest/)

## 파일 구조

```
├── scripts/
│   └── update_dashboard.py    # 메인 스크립트
├── site/
│   └── index.html             # 자동 생성되는 대시보드
├── data/
│   ├── latest.csv             # 최근 실행 결과
│   └── changes_log.json       # 변동사항 이력
└── .github/workflows/
    └── update.yml             # 자동 실행 설정
```

## 로컬 실행

```bash
pip install requests
python scripts/update_dashboard.py
```

`site/index.html`을 브라우저에서 열어 확인 가능합니다.

## 라이선스

MIT · Data provided by respective exchanges under their public API terms.

---

**주의**: 본 자료는 정보 제공 목적이며 투자 조언이 아닙니다.
