package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode"
)

type MatchRule struct {
	term    string
	pattern *regexp.Regexp
}

type ReferenceListMatcher struct {
	customers           []MatchRule
	badIPs              []MatchRule
	deniedEntities      []MatchRule
	compromisedAccounts []MatchRule
	paymentCards        []MatchRule
}

func LoadReferenceListMatcher(dir string) (*ReferenceListMatcher, error) {
	customers, err := loadMatchRules(filepath.Join(dir, "customers.txt"))
	if err != nil {
		return nil, err
	}
	badIPs, err := loadMatchRules(filepath.Join(dir, "bad_ips.txt"))
	if err != nil {
		return nil, err
	}
	deniedEntities, err := loadMatchRules(filepath.Join(dir, "denied_entities.txt"))
	if err != nil {
		return nil, err
	}
	compromisedAccounts, err := loadMatchRules(filepath.Join(dir, "compromised_accounts.txt"))
	if err != nil {
		return nil, err
	}
	paymentCards, err := loadMatchRules(filepath.Join(dir, "payment_cards.txt"))
	if err != nil {
		return nil, err
	}

	return &ReferenceListMatcher{
		customers:           customers,
		badIPs:              badIPs,
		deniedEntities:      deniedEntities,
		compromisedAccounts: compromisedAccounts,
		paymentCards:        paymentCards,
	}, nil
}

func loadMatchRules(path string) ([]MatchRule, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open reference list %s: %w", path, err)
	}
	defer file.Close()

	var rules []MatchRule
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		term := strings.TrimSpace(scanner.Text())
		if term == "" || strings.HasPrefix(term, "#") {
			continue
		}
		rules = append(rules, MatchRule{
			term:    term,
			pattern: regexp.MustCompile(buildRulePattern(term)),
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read reference list %s: %w", path, err)
	}
	return rules, nil
}

func buildRulePattern(term string) string {
	quoted := regexp.QuoteMeta(term)
	prefix := `(?i)`
	if startsWithWordChar(term) {
		prefix += `\b`
	}
	if endsWithWordChar(term) {
		quoted += `\b`
	}
	return prefix + quoted
}

func startsWithWordChar(term string) bool {
	r, _ := utf8FirstRune(term)
	return isWordRune(r)
}

func endsWithWordChar(term string) bool {
	r, _ := utf8LastRune(term)
	return isWordRune(r)
}

func utf8FirstRune(s string) (rune, bool) {
	for _, r := range s {
		return r, true
	}
	return 0, false
}

func utf8LastRune(s string) (rune, bool) {
	var out rune
	var ok bool
	for _, r := range s {
		out = r
		ok = true
	}
	return out, ok
}

func isWordRune(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_'
}

func (m *ReferenceListMatcher) Transform(text string) (string, string) {
	if matchesAny(text, m.badIPs) || matchesAny(text, m.compromisedAccounts) {
		return "", "drop"
	}
	if matchesAny(text, m.customers) || matchesAny(text, m.deniedEntities) {
		return text, "route"
	}
	if masked := maskTerms(text, m.paymentCards); masked != text {
		return masked, "mask"
	}
	return text, "keep"
}

func matchesAny(text string, rules []MatchRule) bool {
	for _, rule := range rules {
		if rule.pattern.FindStringIndex(text) != nil {
			return true
		}
	}
	return false
}

func maskTerms(text string, rules []MatchRule) string {
	masked := text
	for _, rule := range rules {
		masked = rule.pattern.ReplaceAllString(masked, "[MASKED_CARD]")
	}
	return masked
}
